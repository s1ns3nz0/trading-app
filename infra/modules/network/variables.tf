variable "environment" {
  type = string
  validation {
    condition     = contains(["prod", "dev"], var.environment)
    error_message = "environment must be prod or dev."
  }
}

variable "tgw_asn" {
  description = "BGP ASN for the Transit Gateway (64512-65534)"
  type        = number
  default     = 64512
}

variable "ou_arn" {
  description = "ARN of the OU whose member accounts will receive the TGW RAM share"
  type        = string
}

variable "inspection_vpc_cidr" {
  description = "CIDR for the central inspection VPC"
  type        = string
  default     = "100.64.0.0/22"
}

variable "availability_zones" {
  type    = list(string)
  default = ["ap-northeast-2a", "ap-northeast-2b", "ap-northeast-2c"]
}

variable "allowed_egress_domains" {
  description = "Domains permitted for outbound HTTPS traffic from all spoke accounts"
  type        = list(string)
  default = [
    ".amazonaws.com",
    ".binance.com",
    ".coingecko.com",
    ".twilio.com",
    ".sendgrid.net",
    ".datadog.com",
    ".datadoghq.com",
    ".pagerduty.com",
  ]
}
