# ──────────────────────────────────────────────
# Lambda assume-role policy document
# ──────────────────────────────────────────────

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ──────────────────────────────────────────────
# Identity Lambda role — DynamoDB + SES + CloudWatch
# ──────────────────────────────────────────────

resource "aws_iam_role" "identity_lambda" {
  name               = "${var.environment}-identity-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Environment = var.environment
    Domain      = "Identity"
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "identity_basic" {
  role       = aws_iam_role.identity_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "identity_dynamo" {
  name = "dynamo-access"
  role = aws_iam_role.identity_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
        ]
        Resource = [
          aws_dynamodb_table.identity.arn,
          "${aws_dynamodb_table.identity.arn}/index/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["ses:SendEmail"]
        Resource = "*"
      },
    ]
  })
}

# ──────────────────────────────────────────────
# Authorizer Lambda role — DynamoDB GetItem only
# ──────────────────────────────────────────────

resource "aws_iam_role" "authorizer_lambda" {
  name               = "${var.environment}-authorizer-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Environment = var.environment
    Domain      = "Identity"
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "authorizer_basic" {
  role       = aws_iam_role.authorizer_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "authorizer_dynamo" {
  name = "revocation-check"
  role = aws_iam_role.authorizer_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = aws_dynamodb_table.identity.arn
      },
    ]
  })
}
