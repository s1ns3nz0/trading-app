resource "aws_sfn_state_machine" "withdrawal_workflow" {
  name     = "${var.env}-withdrawal-workflow"
  role_arn = aws_iam_role.step_fn.arn

  definition = templatefile("${path.module}/step_functions_asl.json", {
    reserve_balance_fn_arn    = aws_lambda_function.reserve_balance.arn
    validate_aml_fn_arn       = aws_lambda_function.validate_aml.arn
    execute_withdrawal_fn_arn = aws_lambda_function.execute_withdrawal.arn
    publish_event_fn_arn      = aws_lambda_function.publish_event.arn
    reject_withdrawal_fn_arn  = aws_lambda_function.reject_withdrawal.arn
    fail_withdrawal_fn_arn    = aws_lambda_function.fail_withdrawal.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_fn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }
}

resource "aws_cloudwatch_log_group" "step_fn" {
  name              = "/aws/states/${var.env}-withdrawal-workflow"
  retention_in_days = 30
}
