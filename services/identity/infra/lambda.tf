# ──────────────────────────────────────────────
# Identity service Lambda (Mangum → FastAPI)
# ──────────────────────────────────────────────

resource "aws_lambda_function" "identity" {
  function_name = "${var.environment}-identity-service"
  role          = aws_iam_role.identity_lambda.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_registry}/identity-service:${var.image_tag}"
  timeout       = 30
  memory_size   = 512

  environment {
    variables = {
      ENVIRONMENT         = var.environment
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.identity.name
      AWS_REGION          = var.aws_region
      JWT_PRIVATE_KEY     = data.aws_secretsmanager_secret_version.jwt_private.secret_string
      JWT_PUBLIC_KEY      = data.aws_secretsmanager_secret_version.jwt_public.secret_string
      SES_ENABLED         = var.environment == "prod" ? "true" : "false"
      SES_FROM_ADDRESS    = "noreply@trading-platform.com"
      APP_BASE_URL        = var.app_base_url
    }
  }

  tags = {
    Environment = var.environment
    Domain      = "Identity"
    ManagedBy   = "terraform"
  }
}

resource "aws_lambda_permission" "identity_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.identity.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.identity.execution_arn}/*/*"
}

# ──────────────────────────────────────────────
# Lambda Authorizer (separate function, minimal memory, 5s timeout)
# ──────────────────────────────────────────────

resource "aws_lambda_function" "authorizer" {
  function_name = "${var.environment}-identity-authorizer"
  role          = aws_iam_role.authorizer_lambda.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_registry}/identity-authorizer:${var.image_tag}"
  timeout       = 5
  memory_size   = 256

  environment {
    variables = {
      IDENTITY_JWKS_URL   = "${aws_apigatewayv2_api.identity.api_endpoint}/auth/.well-known/jwks.json"
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.identity.name
      AWS_REGION          = var.aws_region
    }
  }

  tags = {
    Environment = var.environment
    Domain      = "Identity"
    ManagedBy   = "terraform"
  }
}

resource "aws_lambda_permission" "authorizer_apigw" {
  statement_id  = "AllowAPIGatewayInvokeAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.identity.execution_arn}/*/*"
}

# ──────────────────────────────────────────────
# Secrets Manager references for JWT keys
# ──────────────────────────────────────────────

data "aws_secretsmanager_secret_version" "jwt_private" {
  secret_id = "${var.environment}/identity/jwt-private-key"
}

data "aws_secretsmanager_secret_version" "jwt_public" {
  secret_id = "${var.environment}/identity/jwt-public-key"
}

# ──────────────────────────────────────────────
# Variables
# ──────────────────────────────────────────────

variable "ecr_registry" {
  type        = string
  description = "ECR registry URL (account.dkr.ecr.region.amazonaws.com)"
}

variable "image_tag" {
  type        = string
  description = "Docker image tag to deploy"
  default     = "latest"
}

variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}

variable "app_base_url" {
  type        = string
  description = "Frontend base URL for email verification links"
  default     = "https://app.trading-platform.com"
}
