output "org_id" {
  description = "AWS Organizations ID"
  value       = aws_organizations_organization.this.id
}

output "root_id" {
  description = "Organizations root ID"
  value       = aws_organizations_organization.this.roots[0].id
}

output "ou_production_id" {
  description = "Production OU ID"
  value       = aws_organizations_organizational_unit.production.id
}

output "ou_development_id" {
  description = "Development OU ID"
  value       = aws_organizations_organizational_unit.development.id
}

output "ou_security_id" {
  description = "Security OU ID"
  value       = aws_organizations_organizational_unit.security.id
}

output "ou_infrastructure_id" {
  description = "Infrastructure OU ID"
  value       = aws_organizations_organizational_unit.infrastructure.id
}
