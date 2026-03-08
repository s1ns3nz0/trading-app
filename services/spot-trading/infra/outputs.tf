output "db_cluster_endpoint" {
  description = "Aurora writer endpoint"
  value       = aws_rds_cluster.spot_db.endpoint
}

output "db_reader_endpoint" {
  description = "Aurora reader endpoint"
  value       = aws_rds_cluster.spot_db.reader_endpoint
}

output "redis_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = aws_elasticache_replication_group.spot_redis.primary_endpoint_address
}

output "ws_api_endpoint" {
  description = "API Gateway WebSocket endpoint"
  value       = "${aws_apigatewayv2_api.spot_ws.api_endpoint}/${aws_apigatewayv2_stage.prod.name}"
}

output "ws_connections_table" {
  description = "DynamoDB WebSocket connections table name"
  value       = aws_dynamodb_table.ws_connections.name
}
