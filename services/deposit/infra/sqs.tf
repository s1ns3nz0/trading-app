resource "aws_sqs_queue" "deposit_dlq" {
  name                      = "${var.env}-deposit-dlq"
  message_retention_seconds = 1209600 # 14 days

  tags = { Service = "deposit", Environment = var.env }
}

resource "aws_sqs_queue" "deposit_tasks" {
  name                       = "${var.env}-deposit-tasks"
  visibility_timeout_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.deposit_dlq.arn
    maxReceiveCount     = 3
  })

  tags = { Service = "deposit", Environment = var.env }
}
