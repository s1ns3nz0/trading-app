variable "transit_gateway_id_prod" {
  description = "Production TGW ID from network account"
  type        = string
}

variable "org_id" {
  description = "AWS Organizations ID"
  type        = string
}

variable "log_archive_bucket" {
  description = "S3 bucket for CloudTrail logs (in log-archive account)"
  type        = string
}

variable "aws_region" {
  description = "AWS deployment region"
  type        = string
  default     = "ap-northeast-2"
}
