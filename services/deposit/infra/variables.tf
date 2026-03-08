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

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS Fargate"
  type        = list(string)
}

variable "db_subnet_group" {
  description = "DB subnet group name"
  type        = string
}

variable "ecr_registry" {
  description = "ECR registry URL"
  type        = string
}

variable "image_tag" {
  description = "Docker image tag"
  type        = string
  default     = "latest"
}

variable "spot_trading_internal_url" {
  description = "Spot trading service internal URL"
  type        = string
}

variable "spot_trading_event_bus_arn" {
  description = "ARN of spot trading EventBridge bus"
  type        = string
}

variable "notification_event_bus_arn" {
  description = "ARN of notification EventBridge bus"
  type        = string
}

variable "internal_token" {
  description = "Shared secret for inter-service authentication"
  type        = string
  sensitive   = true
}
