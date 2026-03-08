resource "aws_rds_cluster" "deposit" {
  cluster_identifier          = "${var.env}-deposit-aurora"
  engine                      = "aurora-postgresql"
  engine_version              = "15.4"
  database_name               = "finance"
  master_username             = "deposit_admin"
  manage_master_user_password = true
  db_subnet_group_name        = var.db_subnet_group
  vpc_security_group_ids      = [aws_security_group.aurora.id]
  backup_retention_period     = 7
  deletion_protection         = true

  tags = {
    Service     = "deposit"
    Environment = var.env
  }
}

resource "aws_rds_cluster_instance" "deposit" {
  count              = var.env == "prod" ? 2 : 1
  cluster_identifier = aws_rds_cluster.deposit.id
  instance_class     = "db.r6g.large"
  engine             = aws_rds_cluster.deposit.engine
  engine_version     = aws_rds_cluster.deposit.engine_version
}

resource "aws_security_group" "aurora" {
  name        = "${var.env}-deposit-aurora-sg"
  description = "Aurora PostgreSQL for deposit service"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  tags = { Name = "${var.env}-deposit-aurora-sg" }
}
