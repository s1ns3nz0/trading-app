terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "trading-platform-tfstate-org"
    key            = "org/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "trading-platform-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1" # Organizations API is global, but control plane is us-east-1
  alias  = "master"
}

# ──────────────────────────────────────────────
# AWS Organizations
# ──────────────────────────────────────────────

resource "aws_organizations_organization" "this" {
  aws_service_access_principals = [
    "cloudtrail.amazonaws.com",
    "config.amazonaws.com",
    "guardduty.amazonaws.com",
    "securityhub.amazonaws.com",
    "sso.amazonaws.com",
    "tagpolicies.tag.amazonaws.com",
    "cost-optimization-hub.bcm.amazonaws.com",
  ]

  feature_set          = "ALL"
  enabled_policy_types = ["SERVICE_CONTROL_POLICY", "TAG_POLICY"]
}

# ──────────────────────────────────────────────
# Organizational Units
# ──────────────────────────────────────────────

resource "aws_organizations_organizational_unit" "production" {
  name      = "Production"
  parent_id = aws_organizations_organization.this.roots[0].id
}

resource "aws_organizations_organizational_unit" "development" {
  name      = "Development"
  parent_id = aws_organizations_organization.this.roots[0].id
}

resource "aws_organizations_organizational_unit" "security" {
  name      = "Security"
  parent_id = aws_organizations_organization.this.roots[0].id
}

resource "aws_organizations_organizational_unit" "infrastructure" {
  name      = "Infrastructure"
  parent_id = aws_organizations_organization.this.roots[0].id
}

# ──────────────────────────────────────────────
# Service Control Policies
# ──────────────────────────────────────────────

resource "aws_organizations_policy" "deny_root_actions" {
  name        = "DenyRootActions"
  description = "Prevent use of root user credentials in all member accounts"
  type        = "SERVICE_CONTROL_POLICY"

  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DenyRootUser"
        Effect   = "Deny"
        Action   = "*"
        Resource = "*"
        Condition = {
          StringLike = {
            "aws:PrincipalArn" = ["arn:aws:iam::*:root"]
          }
        }
      }
    ]
  })
}

resource "aws_organizations_policy" "deny_leave_org" {
  name        = "DenyLeaveOrganization"
  description = "Prevent member accounts from leaving the organization"
  type        = "SERVICE_CONTROL_POLICY"

  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DenyLeaveOrganization"
        Effect   = "Deny"
        Action   = "organizations:LeaveOrganization"
        Resource = "*"
      }
    ]
  })
}

resource "aws_organizations_policy" "require_approved_regions" {
  name        = "RequireApprovedRegions"
  description = "Restrict operations to approved AWS regions only"
  type        = "SERVICE_CONTROL_POLICY"

  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowOnlyApprovedRegions"
        Effect = "Deny"
        NotAction = [
          # Global services — always allowed regardless of region
          "iam:*",
          "organizations:*",
          "support:*",
          "cloudfront:*",
          "waf:*",
          "route53:*",
          "sts:*",
          "s3:GetBucketLocation",
          "s3:ListAllMyBuckets",
        ]
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "aws:RequestedRegion" = var.approved_regions
          }
        }
      }
    ]
  })
}

resource "aws_organizations_policy" "deny_prod_dev_peering" {
  name        = "DenyProdDevNetworkPeering"
  description = "Prevent Production and Development Transit Gateways from peering with each other"
  type        = "SERVICE_CONTROL_POLICY"

  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DenyTGWPeeringAcrossEnvs"
        Effect = "Deny"
        Action = [
          "ec2:CreateTransitGatewayPeeringAttachment",
          "ec2:AcceptTransitGatewayPeeringAttachment",
        ]
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "aws:ResourceOrgPaths" = ["o-*/ou-prod-*/", "o-*/ou-dev-*/"]
          }
        }
      }
    ]
  })
}

# ──────────────────────────────────────────────
# SCP Attachments
# ──────────────────────────────────────────────

resource "aws_organizations_policy_attachment" "deny_root_root" {
  policy_id = aws_organizations_policy.deny_root_actions.id
  target_id = aws_organizations_organization.this.roots[0].id
}

resource "aws_organizations_policy_attachment" "deny_leave_root" {
  policy_id = aws_organizations_policy.deny_leave_org.id
  target_id = aws_organizations_organization.this.roots[0].id
}

resource "aws_organizations_policy_attachment" "approved_regions_root" {
  policy_id = aws_organizations_policy.require_approved_regions.id
  target_id = aws_organizations_organization.this.roots[0].id
}

resource "aws_organizations_policy_attachment" "deny_peering_prod" {
  policy_id = aws_organizations_policy.deny_prod_dev_peering.id
  target_id = aws_organizations_organizational_unit.production.id
}

resource "aws_organizations_policy_attachment" "deny_peering_dev" {
  policy_id = aws_organizations_policy.deny_prod_dev_peering.id
  target_id = aws_organizations_organizational_unit.development.id
}

# ──────────────────────────────────────────────
# Tag Policies
# ──────────────────────────────────────────────

resource "aws_organizations_policy" "required_tags" {
  name        = "RequiredTags"
  description = "Enforce mandatory tags on all taggable resources"
  type        = "TAG_POLICY"

  content = jsonencode({
    tags = {
      Company = {
        tag_key = {
          "@@assign" = "Company"
        }
        tag_value = {
          "@@assign" = ["TradingPlatform"]
        }
        enforced_for = {
          "@@assign" = ["ec2:instance", "ec2:vpc", "ecs:cluster", "ecs:service", "lambda:function", "rds:db", "elasticache:cluster", "msk:cluster", "eks:cluster", "s3:bucket"]
        }
      }
      Environment = {
        tag_key = {
          "@@assign" = "Environment"
        }
        tag_value = {
          "@@assign" = ["prod", "dev", "staging"]
        }
        enforced_for = {
          "@@assign" = ["ec2:instance", "ec2:vpc", "ecs:cluster", "ecs:service", "lambda:function", "rds:db", "elasticache:cluster", "msk:cluster", "eks:cluster", "s3:bucket"]
        }
      }
      Domain = {
        tag_key = {
          "@@assign" = "Domain"
        }
        tag_value = {
          "@@assign" = ["SpotTrading", "FuturesTrading", "Deposit", "Withdrawal", "Identity", "MarketData", "Notification", "RiskCompliance", "Security", "Network", "Shared"]
        }
        enforced_for = {
          "@@assign" = ["ec2:instance", "ecs:cluster", "ecs:service", "lambda:function", "rds:db", "elasticache:cluster", "msk:cluster", "eks:cluster"]
        }
      }
      CostCenter = {
        tag_key = {
          "@@assign" = "CostCenter"
        }
        tag_value = {
          "@@assign" = ["CC-SPOT", "CC-FUTURES", "CC-DEPOSIT", "CC-WITHDRAW", "CC-IDENTITY", "CC-MARKET", "CC-NOTIFY", "CC-RISK", "CC-SECURITY", "CC-NETWORK", "CC-SHARED"]
        }
        enforced_for = {
          "@@assign" = ["ec2:instance", "ecs:cluster", "ecs:service", "lambda:function", "rds:db", "elasticache:cluster", "msk:cluster", "eks:cluster"]
        }
      }
      Team = {
        tag_key = {
          "@@assign" = "Team"
        }
        tag_value = {
          "@@assign" = ["backend", "frontend", "infra", "security", "data"]
        }
        enforced_for = {
          "@@assign" = ["ec2:instance", "ecs:cluster", "lambda:function"]
        }
      }
      ManagedBy = {
        tag_key = {
          "@@assign" = "ManagedBy"
        }
        tag_value = {
          "@@assign" = ["terraform", "manual"]
        }
        enforced_for = {
          "@@assign" = ["ec2:instance", "ec2:vpc", "ecs:cluster", "lambda:function", "rds:db", "eks:cluster"]
        }
      }
    }
  })
}

resource "aws_organizations_policy_attachment" "required_tags_root" {
  policy_id = aws_organizations_policy.required_tags.id
  target_id = aws_organizations_organization.this.roots[0].id
}

# ──────────────────────────────────────────────
# AWS Cost Categories (3-level hierarchy)
# ──────────────────────────────────────────────

resource "aws_ce_cost_category" "by_company" {
  name         = "Company"
  rule_version = "CostCategoryExpression.v1"

  rule {
    value = "TradingPlatform"
    rule {
      tags {
        key    = "Company"
        values = ["TradingPlatform"]
      }
    }
  }

  default_value = "Untagged"
}

resource "aws_ce_cost_category" "by_domain" {
  name         = "Domain"
  rule_version = "CostCategoryExpression.v1"

  dynamic "rule" {
    for_each = local.domain_cost_centers

    content {
      value = rule.key
      rule {
        tags {
          key    = "CostCenter"
          values = [rule.value]
        }
      }
    }
  }

  default_value = "Untagged"
}

resource "aws_ce_cost_category" "by_environment" {
  name         = "Environment"
  rule_version = "CostCategoryExpression.v1"

  rule {
    value = "Production"
    rule {
      tags {
        key    = "Environment"
        values = ["prod"]
      }
    }
  }

  rule {
    value = "Development"
    rule {
      tags {
        key    = "Environment"
        values = ["dev", "staging"]
      }
    }
  }

  default_value = "Untagged"
}
