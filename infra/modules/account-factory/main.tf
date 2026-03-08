terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ──────────────────────────────────────────────
# VPC — one per account, fixed CIDR from input
# ──────────────────────────────────────────────

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.account_name}-vpc"
  cidr = var.vpc_cidr

  azs             = var.availability_zones
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  enable_nat_gateway   = true
  single_nat_gateway   = var.environment == "dev"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = local.common_tags
}

# ──────────────────────────────────────────────
# CloudTrail — account-level trail → log-archive S3
# ──────────────────────────────────────────────

resource "aws_cloudtrail" "this" {
  name                          = "${var.account_name}-trail"
  s3_bucket_name                = var.log_archive_bucket
  s3_key_prefix                 = var.account_name
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true
  cloud_watch_logs_group_arn    = "${aws_cloudwatch_log_group.cloudtrail.arn}:*"
  cloud_watch_logs_role_arn     = aws_iam_role.cloudtrail.arn

  event_selector {
    read_write_type           = "All"
    include_management_events = true
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "cloudtrail" {
  name              = "/aws/cloudtrail/${var.account_name}"
  retention_in_days = 90
  tags              = local.common_tags
}

resource "aws_iam_role" "cloudtrail" {
  name = "CloudTrailRole-${var.account_name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "cloudtrail_logs" {
  name = "CloudTrailLogsPolicy"
  role = aws_iam_role.cloudtrail.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.cloudtrail.arn}:*"
    }]
  })
}

# ──────────────────────────────────────────────
# GuardDuty — delegated finding publication to security account
# ──────────────────────────────────────────────

resource "aws_guardduty_detector" "this" {
  enable = true

  datasources {
    s3_logs {
      enable = true
    }
    kubernetes {
      audit_logs { enable = var.has_eks }
    }
    malware_protection {
      scan_ec2_instance_with_findings {
        ebs_volumes { enable = true }
      }
    }
  }

  tags = local.common_tags
}

# ──────────────────────────────────────────────
# EventBridge — custom bus for this domain
# ──────────────────────────────────────────────

resource "aws_cloudwatch_event_bus" "domain" {
  name = "${var.domain}-events"
  tags = local.common_tags
}

resource "aws_cloudwatch_event_bus_policy" "domain" {
  event_bus_name = aws_cloudwatch_event_bus.domain.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowOrgPublish"
        Effect = "Allow"
        Principal = { AWS = "*" }
        Action = ["events:PutEvents"]
        Resource = aws_cloudwatch_event_bus.domain.arn
        Condition = {
          StringEquals = {
            "aws:PrincipalOrgID" = var.org_id
          }
        }
      }
    ]
  })
}

# ──────────────────────────────────────────────
# KMS — CMK for encryption at rest
# ──────────────────────────────────────────────

resource "aws_kms_key" "this" {
  description             = "CMK for ${var.account_name} workloads"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = local.common_tags
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.account_name}"
  target_key_id = aws_kms_key.this.key_id
}

# ──────────────────────────────────────────────
# Transit Gateway attachment
# ──────────────────────────────────────────────

resource "aws_ec2_transit_gateway_vpc_attachment" "this" {
  transit_gateway_id = var.transit_gateway_id
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.private_subnets

  tags = merge(local.common_tags, {
    Name = "${var.account_name}-tgw-attachment"
  })
}

# ──────────────────────────────────────────────
# SSM Parameter Store — export shared values
# ──────────────────────────────────────────────

resource "aws_ssm_parameter" "vpc_id" {
  name  = "/trading/${var.environment}/${var.domain}/vpc-id"
  type  = "String"
  value = module.vpc.vpc_id
  tags  = local.common_tags
}

resource "aws_ssm_parameter" "private_subnet_ids" {
  name  = "/trading/${var.environment}/${var.domain}/private-subnet-ids"
  type  = "StringList"
  value = join(",", module.vpc.private_subnets)
  tags  = local.common_tags
}

resource "aws_ssm_parameter" "kms_key_arn" {
  name  = "/trading/${var.environment}/${var.domain}/kms-key-arn"
  type  = "String"
  value = aws_kms_key.this.arn
  tags  = local.common_tags
}

resource "aws_ssm_parameter" "event_bus_arn" {
  name  = "/trading/${var.environment}/${var.domain}/event-bus-arn"
  type  = "String"
  value = aws_cloudwatch_event_bus.domain.arn
  tags  = local.common_tags
}
