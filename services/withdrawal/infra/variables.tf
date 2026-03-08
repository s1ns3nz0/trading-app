variable "env" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "ap-northeast-2"
}

variable "account_id" {
  description = "AWS account ID"
  type        = string
}

variable "finance_event_bus_name" {
  description = "Name of the finance-events EventBridge bus (shared with deposit-service)"
  type        = string
  default     = "finance-events"
}

variable "riskcompliance_event_bus_arn" {
  description = "ARN of the risk/compliance account event bus"
  type        = string
}

variable "notification_event_bus_arn" {
  description = "ARN of the notification account event bus"
  type        = string
}

variable "eventbridge_role_arn" {
  description = "IAM role ARN for EventBridge cross-account delivery"
  type        = string
}

variable "aurora_cluster_endpoint" {
  description = "Aurora PostgreSQL cluster endpoint (shared finance cluster)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for ECS service"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS tasks"
  type        = list(string)
}

variable "ecs_cluster_id" {
  description = "ECS cluster ID"
  type        = string
}

variable "ecr_image_uri" {
  description = "ECR image URI for the withdrawal service"
  type        = string
}

variable "spot_trading_internal_url" {
  description = "Internal URL for spot-trading service"
  type        = string
  default     = "http://spot-trading:8000"
}
