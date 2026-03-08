# ──────────────────────────────────────────────
# API Gateway HTTP API
# ──────────────────────────────────────────────

resource "aws_apigatewayv2_api" "identity" {
  name          = "${var.environment}-identity-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins     = var.allowed_origins
    allow_methods     = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
    allow_headers     = ["Authorization", "Content-Type"]
    allow_credentials = true
    max_age           = 3600
  }

  tags = {
    Environment = var.environment
    Domain      = "Identity"
    ManagedBy   = "terraform"
  }
}

# JWT Lambda Authorizer
resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id                            = aws_apigatewayv2_api.identity.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.authorizer.invoke_arn
  name                              = "jwt-authorizer"
  authorizer_result_ttl_in_seconds  = 300
  identity_sources                  = ["$request.header.Authorization"]
}

# Lambda integration
resource "aws_apigatewayv2_integration" "identity" {
  api_id                 = aws_apigatewayv2_api.identity.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.identity.invoke_arn
  payload_format_version = "2.0"
}

# ──────────────────────────────────────────────
# Public routes — no authorizer
# ──────────────────────────────────────────────

locals {
  public_routes = toset([
    "POST /auth/login",
    "POST /auth/register",
    "POST /auth/refresh",
    "POST /auth/logout",
    "POST /auth/verify-email",
    "POST /auth/resend-verification",
    "GET /auth/.well-known/jwks.json",
    "GET /health",
  ])

  protected_routes = toset([
    "GET /users/me",
    "PATCH /users/me",
    "POST /auth/totp/enable",
    "POST /auth/totp/verify",
  ])
}

resource "aws_apigatewayv2_route" "public" {
  for_each  = local.public_routes
  api_id    = aws_apigatewayv2_api.identity.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.identity.id}"
}

# ──────────────────────────────────────────────
# Protected routes — require JWT authorizer
# ──────────────────────────────────────────────

resource "aws_apigatewayv2_route" "protected" {
  for_each           = local.protected_routes
  api_id             = aws_apigatewayv2_api.identity.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.identity.id}"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  authorization_type = "CUSTOM"
}

# Default stage with auto-deploy
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.identity.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gw.arn
  }
}

resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/apigateway/${var.environment}-identity-api"
  retention_in_days = 30
}

# ──────────────────────────────────────────────
# Variables
# ──────────────────────────────────────────────

variable "allowed_origins" {
  type        = list(string)
  description = "CORS allowed origins"
  default     = ["https://app.trading-platform.com"]
}

# ──────────────────────────────────────────────
# Outputs
# ──────────────────────────────────────────────

output "api_endpoint" {
  value = aws_apigatewayv2_api.identity.api_endpoint
}
