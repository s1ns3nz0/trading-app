terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket         = "trading-platform-tfstate-org"
    key            = "prod/spot-trading/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "trading-platform-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = "ap-northeast-2"

  assume_role {
    role_arn = "arn:aws:iam::${var.account_id}:role/TerraformExecutionRole"
  }

  default_tags {
    tags = {
      Company     = "TradingPlatform"
      Environment = "prod"
      Domain      = "SpotTrading"
      CostCenter  = "CC-SPOT"
      Team        = "backend"
      ManagedBy   = "terraform"
    }
  }
}

# ──────────────────────────────────────────────
# Account Foundation (factory module)
# ──────────────────────────────────────────────

module "account" {
  source = "../../../modules/account-factory"

  account_name = "spot-trading-prod"
  environment  = "prod"
  domain       = "SpotTrading"
  cost_center  = "CC-SPOT"
  team         = "backend"

  vpc_cidr             = "10.10.0.0/16"
  private_subnet_cidrs = ["10.10.0.0/19", "10.10.32.0/19", "10.10.64.0/19"]
  public_subnet_cidrs  = ["10.10.128.0/20", "10.10.144.0/20", "10.10.160.0/20"]

  transit_gateway_id = var.transit_gateway_id_prod
  org_id             = var.org_id
  log_archive_bucket = var.log_archive_bucket
  has_eks            = true
}

# ──────────────────────────────────────────────
# EKS Cluster — SpotTrading order engine
# ──────────────────────────────────────────────

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "spot-trading-prod"
  cluster_version = "1.31"

  vpc_id     = module.account.vpc_id
  subnet_ids = module.account.private_subnet_ids

  cluster_endpoint_private_access = true
  cluster_endpoint_public_access  = false # Access only via VPN/bastion

  cluster_addons = {
    coredns                = { most_recent = true }
    kube-proxy             = { most_recent = true }
    vpc-cni                = { most_recent = true }
    aws-ebs-csi-driver     = { most_recent = true }
    aws-efs-csi-driver     = { most_recent = true }
  }

  eks_managed_node_groups = {
    # Order engine — latency-sensitive, CPU-optimized
    order_engine = {
      name           = "order-engine"
      instance_types = ["c6i.xlarge"]
      min_size       = 3
      max_size       = 10
      desired_size   = 3

      labels = {
        workload = "order-engine"
        domain   = "spot-trading"
      }

      taints = [{
        key    = "workload"
        value  = "order-engine"
        effect = "NO_SCHEDULE"
      }]
    }

    # General workloads — API servers, websocket gateways
    general = {
      name           = "general"
      instance_types = ["m6i.large"]
      min_size       = 2
      max_size       = 8
      desired_size   = 2
    }
  }

  tags = {
    Domain     = "SpotTrading"
    CostCenter = "CC-SPOT"
  }
}

# ──────────────────────────────────────────────
# Aurora PostgreSQL — spot order/trade history
# ──────────────────────────────────────────────

resource "aws_rds_cluster" "spot" {
  cluster_identifier = "spot-trading-prod"
  engine             = "aurora-postgresql"
  engine_version     = "16.2"
  database_name      = "spot_trading"
  master_username    = "spot_admin"

  # Password from Secrets Manager (rotation enabled)
  manage_master_user_password = true
  master_user_secret_kms_key_id = module.account.kms_key_id

  db_subnet_group_name   = aws_db_subnet_group.spot.name
  vpc_security_group_ids = [aws_security_group.aurora.id]

  storage_encrypted = true
  kms_key_id        = module.account.kms_key_arn

  backup_retention_period   = 14
  preferred_backup_window   = "02:00-03:00"
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "spot-trading-prod-final"

  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = { Name = "spot-trading-aurora-prod" }
}

resource "aws_rds_cluster_instance" "spot" {
  count              = 2 # writer + reader
  identifier         = "spot-trading-prod-${count.index}"
  cluster_identifier = aws_rds_cluster.spot.id
  instance_class     = "db.r7g.large"
  engine             = aws_rds_cluster.spot.engine
  engine_version     = aws_rds_cluster.spot.engine_version

  performance_insights_enabled          = true
  performance_insights_kms_key_id       = module.account.kms_key_arn
  performance_insights_retention_period = 7

  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.rds_enhanced_monitoring.arn
}

resource "aws_db_subnet_group" "spot" {
  name       = "spot-trading-prod"
  subnet_ids = module.account.private_subnet_ids
  tags       = { Name = "spot-trading-prod-subnet-group" }
}

resource "aws_security_group" "aurora" {
  name        = "aurora-spot-prod"
  description = "Allow PostgreSQL from EKS node groups only"
  vpc_id      = module.account.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "rds_enhanced_monitoring" {
  name = "rds-enhanced-monitoring-spot-prod"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_enhanced_monitoring" {
  role       = aws_iam_role.rds_enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ──────────────────────────────────────────────
# ElastiCache Redis — order book & session cache
# ──────────────────────────────────────────────

resource "aws_elasticache_replication_group" "spot" {
  replication_group_id = "spot-trading-prod"
  description          = "Order book and trading session cache"

  node_type            = "cache.r7g.large"
  num_node_groups      = 3  # Cluster mode with 3 shards
  replicas_per_node_group = 1

  engine_version       = "7.2"
  parameter_group_name = "default.redis7.cluster.on"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.spot.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = module.account.kms_key_arn

  automatic_failover_enabled = true
  multi_az_enabled           = true

  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.redis.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "slow-log"
  }

  tags = { Name = "spot-trading-redis-prod" }
}

resource "aws_elasticache_subnet_group" "spot" {
  name       = "spot-trading-prod"
  subnet_ids = module.account.private_subnet_ids
}

resource "aws_security_group" "redis" {
  name        = "redis-spot-prod"
  description = "Allow Redis from EKS node groups only"
  vpc_id      = module.account.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
}

resource "aws_cloudwatch_log_group" "redis" {
  name              = "/aws/elasticache/spot-trading-prod"
  retention_in_days = 14
}

# ──────────────────────────────────────────────
# DynamoDB — spot orders (single-table design)
# ──────────────────────────────────────────────

resource "aws_dynamodb_table" "spot_orders" {
  name         = "spot-orders-prod"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "GSI2"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = module.account.kms_key_arn
  }

  point_in_time_recovery {
    enabled = true
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = { Name = "spot-orders-prod" }
}
