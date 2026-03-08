# ──────────────────────────────────────────────
# SES — email sending for identity verification
# ──────────────────────────────────────────────

resource "aws_ses_domain_identity" "trading" {
  domain = "trading-platform.com"
}

resource "aws_ses_domain_dkim" "trading" {
  domain = aws_ses_domain_identity.trading.domain
}

# Route53 records for DKIM verification (assumes hosted zone exists)
data "aws_route53_zone" "trading" {
  name         = "trading-platform.com"
  private_zone = false
}

resource "aws_route53_record" "ses_dkim" {
  count   = 3
  zone_id = data.aws_route53_zone.trading.zone_id
  name    = "${aws_ses_domain_dkim.trading.dkim_tokens[count.index]}._domainkey.trading-platform.com"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_ses_domain_dkim.trading.dkim_tokens[count.index]}.dkim.amazonses.com"]
}

# CloudWatch alarm for SES bounce rate (> 5% triggers alert)
resource "aws_cloudwatch_metric_alarm" "ses_bounce_rate" {
  alarm_name          = "${var.environment}-ses-bounce-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Reputation.BounceRate"
  namespace           = "AWS/SES"
  period              = 86400
  statistic           = "Average"
  threshold           = 0.05
  alarm_description   = "SES bounce rate exceeded 5%"
}
