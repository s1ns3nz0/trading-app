variable "account_name" {
  description = "Unique name for this account (e.g. spot-trading-prod)"
  type        = string
}

variable "environment" {
  description = "Deployment environment: prod or dev"
  type        = string

  validation {
    condition     = contains(["prod", "dev"], var.environment)
    error_message = "environment must be 'prod' or 'dev'."
  }
}

variable "domain" {
  description = "DDD bounded context name (e.g. SpotTrading)"
  type        = string

  validation {
    condition = contains([
      "SpotTrading", "FuturesTrading", "Deposit", "Withdrawal",
      "Identity", "MarketData", "Notification", "RiskCompliance",
      "Security", "Network", "Shared"
    ], var.domain)
    error_message = "domain must be a valid DDD bounded context."
  }
}

variable "cost_center" {
  description = "Cost center code for billing allocation (e.g. CC-SPOT)"
  type        = string
}

variable "team" {
  description = "Owning team (backend | frontend | infra | security | data)"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block — must not overlap with other accounts"
  type        = string
}

variable "availability_zones" {
  description = "List of AZs to use within the region"
  type        = list(string)
  default     = ["ap-northeast-2a", "ap-northeast-2b", "ap-northeast-2c"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ)"
  type        = list(string)
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
}

variable "transit_gateway_id" {
  description = "ID of the environment's Transit Gateway (prod or dev)"
  type        = string
}

variable "org_id" {
  description = "AWS Organizations ID for EventBridge bus policy"
  type        = string
}

variable "log_archive_bucket" {
  description = "S3 bucket name in log-archive account for CloudTrail"
  type        = string
}

variable "has_eks" {
  description = "Enable GuardDuty EKS audit log protection for this account"
  type        = bool
  default     = false
}
