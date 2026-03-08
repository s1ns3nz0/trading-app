output "vpc_id" {
  description = "VPC ID for this account"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnets
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnets
}

output "kms_key_arn" {
  description = "ARN of the account-level CMK"
  value       = aws_kms_key.this.arn
}

output "kms_key_id" {
  description = "ID of the account-level CMK"
  value       = aws_kms_key.this.key_id
}

output "event_bus_arn" {
  description = "ARN of the domain EventBridge custom bus"
  value       = aws_cloudwatch_event_bus.domain.arn
}

output "event_bus_name" {
  description = "Name of the domain EventBridge custom bus"
  value       = aws_cloudwatch_event_bus.domain.name
}

output "tgw_attachment_id" {
  description = "Transit Gateway VPC attachment ID"
  value       = aws_ec2_transit_gateway_vpc_attachment.this.id
}

output "guardduty_detector_id" {
  description = "GuardDuty detector ID"
  value       = aws_guardduty_detector.this.id
}
