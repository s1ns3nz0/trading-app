terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket         = "trading-terraform-state"
    key            = "market-data/prod/terraform.tfstate"
    region         = "ap-northeast-2"
    encrypt        = true
    dynamodb_table = "trading-terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  tags = {
    Company     = "TradingApp"
    Environment = "prod"
    Domain      = "MarketData"
    CostCenter  = "CC-MARKET"
    Team        = "data"
    ManagedBy   = "terraform"
  }
}

# ─── Account Factory (VPC, CloudTrail, GuardDuty, KMS, TGW attach) ───────────

module "account" {
  source = "../../../infra/modules/account-factory"

  account_name = "market-data-prod"
  environment  = "prod"
  domain       = "MarketData"
  cost_center  = "CC-MARKET"
  team         = "data"

  vpc_cidr             = "10.1.0.0/16"
  private_subnet_cidrs = ["10.1.0.0/19", "10.1.32.0/19", "10.1.64.0/19"]
  public_subnet_cidrs  = ["10.1.128.0/20", "10.1.144.0/20", "10.1.160.0/20"]
  transit_gateway_id   = var.transit_gateway_id_prod
  org_id               = var.org_id
  log_archive_bucket   = var.log_archive_bucket
}

# ─── Security Groups ──────────────────────────────────────────────────────────

resource "aws_security_group" "msk" {
  name        = "market-data-msk"
  description = "MSK Kafka broker security group"
  vpc_id      = module.account.vpc_id

  ingress {
    description = "Kafka TLS from ECS tasks"
    from_port   = 9098
    to_port     = 9098
    protocol    = "tcp"
    self        = true
  }

  ingress {
    description     = "Kafka TLS from Lambda"
    from_port       = 9098
    to_port         = 9098
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_security_group" "redis" {
  name        = "market-data-redis"
  description = "ElastiCache Redis security group"
  vpc_id      = module.account.vpc_id

  ingress {
    description = "Redis from ECS tasks and Lambda"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    self        = true
  }

  ingress {
    description     = "Redis from Lambda"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_security_group" "ecs_tasks" {
  name        = "market-data-ecs-tasks"
  description = "ECS Fargate tasks (ingester, router, api)"
  vpc_id      = module.account.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_security_group" "lambda" {
  name        = "market-data-lambda"
  description = "Lambda functions (ws-gateway, candle-builder)"
  vpc_id      = module.account.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

# Allow MSK SG to accept from ECS SG
resource "aws_security_group_rule" "msk_from_ecs" {
  type                     = "ingress"
  from_port                = 9098
  to_port                  = 9098
  protocol                 = "tcp"
  security_group_id        = aws_security_group.msk.id
  source_security_group_id = aws_security_group.ecs_tasks.id
  description              = "Kafka TLS from ECS tasks"
}

resource "aws_security_group_rule" "redis_from_ecs" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = aws_security_group.redis.id
  source_security_group_id = aws_security_group.ecs_tasks.id
  description              = "Redis from ECS tasks"
}

# ─── ECS Cluster ──────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "market_data" {
  name = "market-data-prod"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.tags
}

resource "aws_ecs_cluster_capacity_providers" "market_data" {
  cluster_name       = aws_ecs_cluster.market_data.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

# ─── MSK Kafka — KRaft mode (no ZooKeeper) ────────────────────────────────────

resource "aws_msk_cluster" "market_data" {
  cluster_name           = "market-data-prod"
  kafka_version          = "3.7.x.kraft"
  number_of_broker_nodes = 3

  broker_node_group_info {
    instance_type   = "kafka.t3.small"
    client_subnets  = module.account.private_subnet_ids
    security_groups = [aws_security_group.msk.id]

    storage_info {
      ebs_storage_info {
        volume_size = 100
      }
    }
  }

  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
    encryption_at_rest {
      data_volume_kms_key_id = module.account.kms_key_id
    }
  }

  client_authentication {
    sasl {
      iam = true
    }
  }

  open_monitoring {
    prometheus {
      jmx_exporter  { enabled_in_broker = true }
      node_exporter { enabled_in_broker = true }
    }
  }

  logging {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = "/msk/market-data-prod"
      }
    }
  }

  tags = local.tags
}

resource "aws_cloudwatch_log_group" "msk" {
  name              = "/msk/market-data-prod"
  retention_in_days = 7
  kms_key_id        = module.account.kms_key_arn
  tags              = local.tags
}

# ─── ElastiCache Redis ────────────────────────────────────────────────────────

resource "aws_elasticache_subnet_group" "market_data" {
  name       = "market-data-prod"
  subnet_ids = module.account.private_subnet_ids
  tags       = local.tags
}

resource "aws_elasticache_replication_group" "market_data" {
  replication_group_id = "market-data-prod"
  description          = "Live market data cache (ticker, orderbook, trades)"
  node_type            = "cache.r7g.medium"
  num_node_groups      = 1
  replicas_per_node_group = 1

  engine_version             = "7.2"
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = module.account.kms_key_arn
  automatic_failover_enabled = true
  multi_az_enabled           = true

  # Eviction policy: keep most recently used data in memory
  parameter_group_name = aws_elasticache_parameter_group.market_data.name

  subnet_group_name  = aws_elasticache_subnet_group.market_data.name
  security_group_ids = [aws_security_group.redis.id]

  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.redis.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "slow-log"
  }

  tags = local.tags
}

resource "aws_elasticache_parameter_group" "market_data" {
  name   = "market-data-prod-redis72"
  family = "redis7"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }
}

resource "aws_cloudwatch_log_group" "redis" {
  name              = "/elasticache/market-data-prod"
  retention_in_days = 7
  kms_key_id        = module.account.kms_key_arn
  tags              = local.tags
}

# ─── DynamoDB — OHLCV Candle History ─────────────────────────────────────────

resource "aws_dynamodb_table" "candles" {
  name         = "market-data-candles"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute { name = "PK"     type = "S" }
  attribute { name = "SK"     type = "N" }
  attribute { name = "GSI1PK" type = "S" }
  attribute { name = "GSI1SK" type = "S" }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = module.account.kms_key_arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = local.tags
}

# ─── DynamoDB — WebSocket Connection Registry ─────────────────────────────────

resource "aws_dynamodb_table" "ws_connections" {
  name         = "market-data-ws-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute { name = "connectionId" type = "S" }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = local.tags
}

# ─── API Gateway WebSocket ────────────────────────────────────────────────────

resource "aws_apigatewayv2_api" "ws" {
  name                       = "market-data-ws"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
  tags                       = local.tags
}

resource "aws_apigatewayv2_stage" "ws_prod" {
  api_id      = aws_apigatewayv2_api.ws.id
  name        = "prod"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.apigw_ws.arn
  }

  tags = local.tags
}

resource "aws_cloudwatch_log_group" "apigw_ws" {
  name              = "/aws/apigateway/market-data-ws"
  retention_in_days = 14
  kms_key_id        = module.account.kms_key_arn
  tags              = local.tags
}

# WS Lambda integrations
resource "aws_apigatewayv2_integration" "connect" {
  api_id           = aws_apigatewayv2_api.ws.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.ws_connect.invoke_arn
}

resource "aws_apigatewayv2_integration" "disconnect" {
  api_id           = aws_apigatewayv2_api.ws.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.ws_disconnect.invoke_arn
}

resource "aws_apigatewayv2_integration" "default" {
  api_id           = aws_apigatewayv2_api.ws.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.ws_default.invoke_arn
}

resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.connect.id}"
}

resource "aws_apigatewayv2_route" "disconnect" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.disconnect.id}"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.default.id}"
}

# ─── IAM — Lambda Execution Role ─────────────────────────────────────────────

resource "aws_iam_role" "lambda_ws" {
  name = "market-data-lambda-ws"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.tags
}

resource "aws_iam_role_policy" "lambda_ws" {
  name = "market-data-lambda-ws-policy"
  role = aws_iam_role.lambda_ws.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Logs"
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
                  "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"]
        Resource = [
          aws_dynamodb_table.ws_connections.arn,
          aws_dynamodb_table.candles.arn,
          "${aws_dynamodb_table.candles.arn}/index/*"
        ]
      },
      {
        Sid    = "ApiGwManage"
        Effect = "Allow"
        Action = ["execute-api:ManageConnections"]
        Resource = "${aws_apigatewayv2_api.ws.execution_arn}/*"
      },
      {
        Sid    = "VPC"
        Effect = "Allow"
        Action = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"]
        Resource = "*"
      },
      {
        Sid    = "KMS"
        Effect = "Allow"
        Action = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = module.account.kms_key_arn
      }
    ]
  })
}

# ─── Lambda — WS Gateway Handlers ────────────────────────────────────────────

data "archive_file" "ws_connect" {
  type        = "zip"
  source_file = "${path.module}/../ws-gateway/connect.py"
  output_path = "${path.module}/.build/ws_connect.zip"
}

data "archive_file" "ws_disconnect" {
  type        = "zip"
  source_file = "${path.module}/../ws-gateway/disconnect.py"
  output_path = "${path.module}/.build/ws_disconnect.zip"
}

data "archive_file" "ws_default" {
  type        = "zip"
  source_file = "${path.module}/../ws-gateway/default.py"
  output_path = "${path.module}/.build/ws_default.zip"
}

resource "aws_lambda_function" "ws_connect" {
  function_name    = "market-data-ws-connect"
  filename         = data.archive_file.ws_connect.output_path
  source_code_hash = data.archive_file.ws_connect.output_base64sha256
  handler          = "connect.handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_ws.arn
  timeout          = 10
  memory_size      = 256

  vpc_config {
    subnet_ids         = module.account.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
    }
  }

  tags = local.tags
}

resource "aws_lambda_function" "ws_disconnect" {
  function_name    = "market-data-ws-disconnect"
  filename         = data.archive_file.ws_disconnect.output_path
  source_code_hash = data.archive_file.ws_disconnect.output_base64sha256
  handler          = "disconnect.handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_ws.arn
  timeout          = 10
  memory_size      = 256

  vpc_config {
    subnet_ids         = module.account.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
    }
  }

  tags = local.tags
}

resource "aws_lambda_function" "ws_default" {
  function_name    = "market-data-ws-default"
  filename         = data.archive_file.ws_default.output_path
  source_code_hash = data.archive_file.ws_default.output_base64sha256
  handler          = "default.handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_ws.arn
  timeout          = 30
  memory_size      = 512

  vpc_config {
    subnet_ids         = module.account.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
      REDIS_URL         = "rediss://${aws_elasticache_replication_group.market_data.primary_endpoint_address}:6379"
      API_GW_ENDPOINT   = "https://${aws_apigatewayv2_api.ws.id}.execute-api.${var.aws_region}.amazonaws.com/prod"
    }
  }

  tags = local.tags
}

# Lambda permissions for API Gateway
resource "aws_lambda_permission" "ws_connect" {
  statement_id  = "AllowApiGwConnect"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_connect.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*/*"
}

resource "aws_lambda_permission" "ws_disconnect" {
  statement_id  = "AllowApiGwDisconnect"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_disconnect.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*/*"
}

resource "aws_lambda_permission" "ws_default" {
  statement_id  = "AllowApiGwDefault"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_default.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*/*"
}

# ─── Lambda — Candle Builder (MSK triggered) ──────────────────────────────────

resource "aws_iam_role" "lambda_candle" {
  name = "market-data-lambda-candle"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.tags
}

resource "aws_iam_role_policy" "lambda_candle" {
  name = "market-data-lambda-candle-policy"
  role = aws_iam_role.lambda_candle.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Logs"
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.candles.arn
      },
      {
        Sid    = "MSK"
        Effect = "Allow"
        Action = [
          "kafka:DescribeCluster", "kafka:GetBootstrapBrokers",
          "kafka-cluster:Connect", "kafka-cluster:AlterCluster",
          "kafka-cluster:DescribeCluster",
          "kafka-cluster:ReadData", "kafka-cluster:DescribeGroup"
        ]
        Resource = aws_msk_cluster.market_data.arn
      },
      {
        Sid    = "VPC"
        Effect = "Allow"
        Action = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"]
        Resource = "*"
      },
      {
        Sid    = "KMS"
        Effect = "Allow"
        Action = ["kms:Decrypt"]
        Resource = module.account.kms_key_arn
      }
    ]
  })
}

data "archive_file" "candle_builder" {
  type        = "zip"
  source_file = "${path.module}/../candle-builder/handler.py"
  output_path = "${path.module}/.build/candle_builder.zip"
}

resource "aws_lambda_function" "candle_builder" {
  function_name    = "market-data-candle-builder"
  filename         = data.archive_file.candle_builder.output_path
  source_code_hash = data.archive_file.candle_builder.output_base64sha256
  handler          = "handler.handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_candle.arn
  timeout          = 300
  memory_size      = 512

  vpc_config {
    subnet_ids         = module.account.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      CANDLES_TABLE = aws_dynamodb_table.candles.name
    }
  }

  tags = local.tags
}

resource "aws_lambda_event_source_mapping" "candle_builder_msk" {
  event_source_arn  = aws_msk_cluster.market_data.arn
  function_name     = aws_lambda_function.candle_builder.arn
  topics            = ["market.candles.1m.v1"]
  starting_position = "TRIM_HORIZON"

  # Batch settings for throughput
  batch_size                         = 100
  maximum_batching_window_in_seconds = 5

  # Commit offset only after successful processing
  bisect_batch_on_function_error = true
}
