variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-northeast-2"
}

variable "env" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "vpc_id" {
  description = "VPC ID for spot-trading account"
  type        = string
}

variable "db_subnet_group" {
  description = "RDS subnet group name"
  type        = string
}

variable "cache_subnet_group" {
  description = "ElastiCache subnet group name"
  type        = string
}

variable "eks_node_sg_id" {
  description = "Security group ID for EKS worker nodes"
  type        = string
}
