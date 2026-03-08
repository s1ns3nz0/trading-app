output "msk_bootstrap_brokers_tls" {
  description = "MSK TLS bootstrap brokers (IAM auth on port 9098)"
  value       = aws_msk_cluster.market_data.bootstrap_brokers_sasl_iam
}

output "redis_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = aws_elasticache_replication_group.market_data.primary_endpoint_address
}

output "candles_table_name" {
  description = "DynamoDB candle history table name"
  value       = aws_dynamodb_table.candles.name
}

output "ws_connections_table_name" {
  description = "DynamoDB WebSocket connections table name"
  value       = aws_dynamodb_table.ws_connections.name
}

output "ws_api_endpoint" {
  description = "API Gateway WebSocket endpoint"
  value       = aws_apigatewayv2_stage.ws_prod.invoke_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name for service deployments"
  value       = aws_ecs_cluster.market_data.name
}

output "ecs_tasks_sg_id" {
  description = "Security group ID for ECS tasks"
  value       = aws_security_group.ecs_tasks.id
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.account.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.account.private_subnet_ids
}
