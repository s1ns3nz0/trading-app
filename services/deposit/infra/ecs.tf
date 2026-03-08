resource "aws_security_group" "ecs" {
  name        = "${var.env}-deposit-ecs-sg"
  description = "ECS Fargate for deposit service"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.env}-deposit-ecs-sg" }
}

resource "aws_ecs_cluster" "deposit" {
  name = "${var.env}-deposit"
  tags = { Service = "deposit", Environment = var.env }
}

resource "aws_ecs_task_definition" "deposit" {
  family                   = "${var.env}-deposit"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "deposit"
    image     = "${var.ecr_registry}/deposit:${var.image_tag}"
    essential = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "AWS_REGION", value = var.region },
      { name = "STEP_FN_ARN", value = aws_sfn_state_machine.deposit_workflow.arn },
      { name = "EVENTBRIDGE_BUS_NAME", value = aws_cloudwatch_event_bus.finance.name },
      { name = "SPOT_TRADING_INTERNAL_URL", value = var.spot_trading_internal_url },
    ]
    secrets = [
      { name = "DB_URL", valueFrom = aws_rds_cluster.deposit.master_user_secret[0].secret_arn },
      { name = "INTERNAL_TOKEN", valueFrom = "arn:aws:secretsmanager:${var.region}:${var.account_id}:secret:deposit/internal-token" },
      { name = "WEBHOOK_HMAC_SECRET", valueFrom = "arn:aws:secretsmanager:${var.region}:${var.account_id}:secret:deposit/webhook-hmac" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/${var.env}-deposit"
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.env}-deposit"
  retention_in_days = 30
}

resource "aws_ecs_service" "deposit" {
  name            = "${var.env}-deposit"
  cluster         = aws_ecs_cluster.deposit.id
  task_definition = aws_ecs_task_definition.deposit.arn
  desired_count   = var.env == "prod" ? 2 : 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }
}
