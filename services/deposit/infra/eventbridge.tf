resource "aws_cloudwatch_event_bus" "finance" {
  name = "finance-events"
  tags = { Service = "deposit", Environment = var.env }
}

resource "aws_cloudwatch_event_rule" "deposit_confirmed" {
  name           = "${var.env}-deposit-confirmed"
  event_bus_name = aws_cloudwatch_event_bus.finance.name

  event_pattern = jsonencode({
    source      = ["finance.deposit"]
    detail-type = ["DepositConfirmed"]
  })

  tags = { Service = "deposit", Environment = var.env }
}

resource "aws_cloudwatch_event_target" "spot_trading_bus" {
  rule           = aws_cloudwatch_event_rule.deposit_confirmed.name
  event_bus_name = aws_cloudwatch_event_bus.finance.name
  arn            = var.spot_trading_event_bus_arn
  role_arn       = aws_iam_role.eventbridge.arn
}

resource "aws_cloudwatch_event_target" "notification_bus" {
  rule           = aws_cloudwatch_event_rule.deposit_confirmed.name
  event_bus_name = aws_cloudwatch_event_bus.finance.name
  arn            = var.notification_event_bus_arn
  role_arn       = aws_iam_role.eventbridge.arn
}
