variable "approved_regions" {
  description = "List of AWS regions where workloads are allowed to run"
  type        = list(string)
  default     = ["ap-northeast-2", "us-east-1"]
}

variable "master_account_id" {
  description = "AWS account ID of the Organizations management account"
  type        = string
}

variable "log_archive_account_id" {
  description = "AWS account ID of the log-archive account"
  type        = string
}

variable "security_account_id" {
  description = "AWS account ID of the security tooling account"
  type        = string
}

variable "network_account_id" {
  description = "AWS account ID of the network hub account"
  type        = string
}
