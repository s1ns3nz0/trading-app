terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket         = "trading-app-tfstate"
    key            = "spot-trading/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

# ── Aurora PostgreSQL ─────────────────────────────────────────────────────────
resource "aws_rds_cluster" "spot_db" {
  cluster_identifier          = "${var.env}-spot-trading-db"
  engine                      = "aurora-postgresql"
  engine_version              = "16.2"
  database_name               = "spot_trading"
  master_username             = "spot_admin"
  manage_master_user_password = true
  db_subnet_group_name        = var.db_subnet_group
  vpc_security_group_ids      = [aws_security_group.rds_sg.id]

  tags = { Environment = var.env, Service = "spot-trading" }
}

resource "aws_rds_cluster_instance" "writer" {
  identifier         = "${var.env}-spot-db-writer"
  cluster_identifier = aws_rds_cluster.spot_db.id
  instance_class     = "db.r6g.large"
  engine             = aws_rds_cluster.spot_db.engine
}

resource "aws_rds_cluster_instance" "reader" {
  identifier         = "${var.env}-spot-db-reader"
  cluster_identifier = aws_rds_cluster.spot_db.id
  instance_class     = "db.r6g.large"
  engine             = aws_rds_cluster.spot_db.engine
}

# ── ElastiCache Redis ─────────────────────────────────────────────────────────
resource "aws_elasticache_replication_group" "spot_redis" {
  replication_group_id       = "${var.env}-spot-redis"
  description                = "Spot trading order book + pub/sub"
  node_type                  = "cache.r7g.medium"
  num_cache_clusters         = 1
  parameter_group_name       = "default.redis7"
  subnet_group_name          = var.cache_subnet_group
  security_group_ids         = [aws_security_group.redis_sg.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  tags = { Environment = var.env, Service = "spot-trading" }
}

# ── API Gateway WebSocket ─────────────────────────────────────────────────────
resource "aws_apigatewayv2_api" "spot_ws" {
  name                       = "${var.env}-spot-trading-ws"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
}

resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.spot_ws.id
  name        = "prod"
  auto_deploy = true
}

# ── API GW Routes ─────────────────────────────────────────────────────────────
resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.spot_ws.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.ws_connect.id}"
}

resource "aws_apigatewayv2_route" "disconnect" {
  api_id    = aws_apigatewayv2_api.spot_ws.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.ws_disconnect.id}"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.spot_ws.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.ws_default.id}"
}

resource "aws_apigatewayv2_integration" "ws_connect" {
  api_id                    = aws_apigatewayv2_api.spot_ws.id
  integration_type          = "AWS_PROXY"
  integration_uri           = aws_lambda_function.ws_connect.invoke_arn
  content_handling_strategy = "CONVERT_TO_TEXT"
}

resource "aws_apigatewayv2_integration" "ws_disconnect" {
  api_id                    = aws_apigatewayv2_api.spot_ws.id
  integration_type          = "AWS_PROXY"
  integration_uri           = aws_lambda_function.ws_disconnect.invoke_arn
  content_handling_strategy = "CONVERT_TO_TEXT"
}

resource "aws_apigatewayv2_integration" "ws_default" {
  api_id                    = aws_apigatewayv2_api.spot_ws.id
  integration_type          = "AWS_PROXY"
  integration_uri           = aws_lambda_function.ws_default.invoke_arn
  content_handling_strategy = "CONVERT_TO_TEXT"
}

# ── Lambda: WS Connect ────────────────────────────────────────────────────────
resource "aws_lambda_function" "ws_connect" {
  function_name = "${var.env}-spot-ws-connect"
  runtime       = "python3.12"
  handler       = "connect.handler"
  role          = aws_iam_role.lambda_exec.arn
  filename      = "${path.module}/../ws-notifier/connect.zip"
  timeout       = 10

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
    }
  }

  vpc_config {
    subnet_ids         = data.aws_subnets.private.ids
    security_group_ids = [aws_security_group.lambda_sg.id]
  }
}

# ── Lambda: WS Disconnect ─────────────────────────────────────────────────────
resource "aws_lambda_function" "ws_disconnect" {
  function_name = "${var.env}-spot-ws-disconnect"
  runtime       = "python3.12"
  handler       = "disconnect.handler"
  role          = aws_iam_role.lambda_exec.arn
  filename      = "${path.module}/../ws-notifier/disconnect.zip"
  timeout       = 10

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
    }
  }

  vpc_config {
    subnet_ids         = data.aws_subnets.private.ids
    security_group_ids = [aws_security_group.lambda_sg.id]
  }
}

# ── Lambda: WS Default (subscribe/push) ──────────────────────────────────────
resource "aws_lambda_function" "ws_default" {
  function_name = "${var.env}-spot-ws-default"
  runtime       = "python3.12"
  handler       = "default.handler"
  role          = aws_iam_role.lambda_exec.arn
  filename      = "${path.module}/../ws-notifier/default.zip"
  memory_size   = 512
  timeout       = 29

  environment {
    variables = {
      REDIS_URL         = "rediss://${aws_elasticache_replication_group.spot_redis.primary_endpoint_address}:6379"
      APIGW_ENDPOINT    = "https://${aws_apigatewayv2_api.spot_ws.id}.execute-api.${var.aws_region}.amazonaws.com/${aws_apigatewayv2_stage.prod.name}"
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
    }
  }

  vpc_config {
    subnet_ids         = data.aws_subnets.private.ids
    security_group_ids = [aws_security_group.lambda_sg.id]
  }
}

# Lambda permissions for API GW invocation
resource "aws_lambda_permission" "apigw_connect" {
  statement_id  = "AllowAPIGWInvokeConnect"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_connect.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.spot_ws.execution_arn}/*/$connect"
}

resource "aws_lambda_permission" "apigw_disconnect" {
  statement_id  = "AllowAPIGWInvokeDisconnect"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_disconnect.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.spot_ws.execution_arn}/*/$disconnect"
}

resource "aws_lambda_permission" "apigw_default" {
  statement_id  = "AllowAPIGWInvokeDefault"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws_default.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.spot_ws.execution_arn}/*/$default"
}

# ── DynamoDB: WebSocket Connections ──────────────────────────────────────────
resource "aws_dynamodb_table" "ws_connections" {
  name         = "${var.env}-spot-ws-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute {
    name = "connectionId"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { Environment = var.env, Service = "spot-trading" }
}

# ── Security Groups ───────────────────────────────────────────────────────────
resource "aws_security_group" "rds_sg" {
  name   = "${var.env}-spot-rds-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.eks_node_sg_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Environment = var.env }
}

resource "aws_security_group" "redis_sg" {
  name   = "${var.env}-spot-redis-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [var.eks_node_sg_id, aws_security_group.lambda_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Environment = var.env }
}

resource "aws_security_group" "lambda_sg" {
  name   = "${var.env}-spot-lambda-sg"
  vpc_id = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Environment = var.env }
}

# ── IAM Role for Lambda ───────────────────────────────────────────────────────
resource "aws_iam_role" "lambda_exec" {
  name = "${var.env}-spot-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_apigw_dynamo" {
  name = "spot-apigw-dynamo"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["execute-api:ManageConnections"]
        Resource = "${aws_apigatewayv2_api.spot_ws.execution_arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
        ]
        Resource = aws_dynamodb_table.ws_connections.arn
      },
    ]
  })
}

# ── Data Sources ──────────────────────────────────────────────────────────────
data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "tag:Type"
    values = ["private"]
  }
}

# ── CloudWatch Log Groups ─────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "ws_connect" {
  name              = "/aws/lambda/${aws_lambda_function.ws_connect.function_name}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "ws_disconnect" {
  name              = "/aws/lambda/${aws_lambda_function.ws_disconnect.function_name}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "ws_default" {
  name              = "/aws/lambda/${aws_lambda_function.ws_default.function_name}"
  retention_in_days = 7
}
