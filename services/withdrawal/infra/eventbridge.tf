# Reuses finance-events bus created by deposit-service

resource "aws_cloudwatch_event_rule" "withdrawal_executed" {
  name           = "${var.env}-withdrawal-executed"
  event_bus_name = var.finance_event_bus_name

  event_pattern = jsonencode({
    source      = ["finance.withdrawal"]
    detail-type = ["WithdrawalExecuted"]
  })
}

resource "aws_cloudwatch_event_target" "riskcompliance_bus" {
  rule           = aws_cloudwatch_event_rule.withdrawal_executed.name
  event_bus_name = var.finance_event_bus_name
  arn            = var.riskcompliance_event_bus_arn
  role_arn       = var.eventbridge_role_arn
}

resource "aws_cloudwatch_event_target" "notification_bus" {
  rule           = aws_cloudwatch_event_rule.withdrawal_executed.name
  event_bus_name = var.finance_event_bus_name
  arn            = var.notification_event_bus_arn
  role_arn       = var.eventbridge_role_arn
}
