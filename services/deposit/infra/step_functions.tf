resource "aws_sfn_state_machine" "deposit_workflow" {
  name     = "${var.env}-deposit-workflow"
  role_arn = aws_iam_role.step_fn.arn

  definition = templatefile("${path.module}/step_functions_asl.json", {
    check_confirmations_fn_arn = aws_lambda_function.check_confirmations.arn
    credit_balance_fn_arn      = aws_lambda_function.credit_balance.arn
    publish_event_fn_arn       = aws_lambda_function.publish_event.arn
    handle_failure_fn_arn      = aws_lambda_function.handle_failure.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_fn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tags = { Service = "deposit", Environment = var.env }
}

resource "aws_cloudwatch_log_group" "step_fn" {
  name              = "/aws/states/${var.env}-deposit-workflow"
  retention_in_days = 30
}

# Lambda placeholders for Step Functions tasks
resource "aws_lambda_function" "check_confirmations" {
  function_name = "${var.env}-deposit-check-confirmations"
  role          = aws_iam_role.ecs_task.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_registry}/deposit-workers:${var.image_tag}"
  image_config {
    command = ["handlers.check_confirmations.handler"]
  }
  timeout = 30
  environment {
    variables = {
      DB_URL          = aws_rds_cluster.deposit.endpoint
      INTERNAL_URL    = var.spot_trading_internal_url
      INTERNAL_TOKEN  = var.internal_token
    }
  }
}

resource "aws_lambda_function" "credit_balance" {
  function_name = "${var.env}-deposit-credit-balance"
  role          = aws_iam_role.ecs_task.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_registry}/deposit-workers:${var.image_tag}"
  image_config {
    command = ["handlers.credit_balance.handler"]
  }
  timeout = 30
  environment {
    variables = {
      DB_URL          = aws_rds_cluster.deposit.endpoint
      INTERNAL_URL    = var.spot_trading_internal_url
      INTERNAL_TOKEN  = var.internal_token
    }
  }
}

resource "aws_lambda_function" "publish_event" {
  function_name = "${var.env}-deposit-publish-event"
  role          = aws_iam_role.ecs_task.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_registry}/deposit-workers:${var.image_tag}"
  image_config {
    command = ["handlers.publish_event.handler"]
  }
  timeout = 30
  environment {
    variables = {
      DB_URL               = aws_rds_cluster.deposit.endpoint
      EVENTBRIDGE_BUS_NAME = aws_cloudwatch_event_bus.finance.name
    }
  }
}

resource "aws_lambda_function" "handle_failure" {
  function_name = "${var.env}-deposit-handle-failure"
  role          = aws_iam_role.ecs_task.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_registry}/deposit-workers:${var.image_tag}"
  image_config {
    command = ["handlers.handle_failure.handler"]
  }
  timeout = 30
  environment {
    variables = {
      DB_URL = aws_rds_cluster.deposit.endpoint
    }
  }
}
