output "transit_gateway_id" {
  description = "Transit Gateway ID — pass to account-factory spoke accounts"
  value       = aws_ec2_transit_gateway.this.id
}

output "transit_gateway_arn" {
  value = aws_ec2_transit_gateway.this.arn
}

output "inspection_vpc_id" {
  value = aws_vpc.inspection.id
}

output "firewall_arn" {
  value = aws_networkfirewall_firewall.this.arn
}

output "spoke_route_table_id" {
  description = "TGW route table ID to associate with all spoke VPC attachments"
  value       = aws_ec2_transit_gateway_route_table.spokes.id
}
