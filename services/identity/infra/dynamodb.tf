# DynamoDB single-table for Identity service
# Deployed per-environment via the identity account Terraform

resource "aws_dynamodb_table" "identity" {
  name         = "trading-identity"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # GSI1 — lookup user by email
  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  tags = {
    Name       = "trading-identity"
    Domain     = "Identity"
    CostCenter = "CC-IDENTITY"
    ManagedBy  = "terraform"
  }
}

variable "kms_key_arn" {
  type = string
}

output "table_name" {
  value = aws_dynamodb_table.identity.name
}

output "table_arn" {
  value = aws_dynamodb_table.identity.arn
}
