variable "account_id" {
  description = "AWS Account ID for the spot-trading-prod account"
  type        = string
}

variable "org_id" {
  description = "AWS Organizations ID"
  type        = string
}

variable "transit_gateway_id_prod" {
  description = "Transit Gateway ID from the network-prod account"
  type        = string
}

variable "log_archive_bucket" {
  description = "S3 bucket name in log-archive account for CloudTrail"
  type        = string
}
