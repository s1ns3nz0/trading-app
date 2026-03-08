terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ──────────────────────────────────────────────
# Transit Gateway — one per environment (prod / dev)
# Cross-account RAM share to all OU member accounts
# ──────────────────────────────────────────────

resource "aws_ec2_transit_gateway" "this" {
  description                     = "TGW-${var.environment} — Hub for ${var.environment} accounts"
  amazon_side_asn                 = var.tgw_asn
  auto_accept_shared_attachments  = "enable"
  default_route_table_association = "disable"
  default_route_table_propagation = "disable"
  dns_support                     = "enable"
  vpn_ecmp_support                = "enable"

  tags = merge(local.common_tags, {
    Name = "TGW-${upper(var.environment)}"
  })
}

# RAM share — allows member accounts in the OU to attach their VPCs
resource "aws_ram_resource_share" "tgw" {
  name                      = "TGW-${var.environment}-Share"
  allow_external_principals = false
  tags                      = local.common_tags
}

resource "aws_ram_resource_association" "tgw" {
  resource_arn       = aws_ec2_transit_gateway.this.arn
  resource_share_arn = aws_ram_resource_share.tgw.arn
}

resource "aws_ram_principal_association" "ou" {
  principal          = var.ou_arn
  resource_share_arn = aws_ram_resource_share.tgw.arn
}

# ──────────────────────────────────────────────
# Inspection VPC — centralized egress/ingress
# ──────────────────────────────────────────────

resource "aws_vpc" "inspection" {
  cidr_block           = var.inspection_vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, { Name = "inspection-vpc-${var.environment}" })
}

resource "aws_subnet" "firewall" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.inspection.id
  cidr_block        = cidrsubnet(var.inspection_vpc_cidr, 4, count.index)
  availability_zone = var.availability_zones[count.index]

  tags = merge(local.common_tags, { Name = "firewall-subnet-${var.environment}-${count.index}" })
}

resource "aws_subnet" "tgw_attach" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.inspection.id
  cidr_block        = cidrsubnet(var.inspection_vpc_cidr, 4, count.index + 3)
  availability_zone = var.availability_zones[count.index]

  tags = merge(local.common_tags, { Name = "tgw-attach-subnet-${var.environment}-${count.index}" })
}

# ──────────────────────────────────────────────
# AWS Network Firewall — stateful Suricata rules
# ──────────────────────────────────────────────

resource "aws_networkfirewall_rule_group" "domain_allowlist" {
  name     = "egress-domain-allowlist-${var.environment}"
  type     = "STATEFUL"
  capacity = 100

  rule_group {
    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }
    rules_source {
      rules_source_list {
        generated_rules_type = "ALLOWLIST"
        target_types         = ["HTTP_HOST", "TLS_SNI"]
        targets              = var.allowed_egress_domains
      }
    }
  }

  tags = local.common_tags
}

resource "aws_networkfirewall_rule_group" "threat_signatures" {
  name     = "threat-signatures-${var.environment}"
  type     = "STATEFUL"
  capacity = 1000

  rule_group {
    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }
    rules_source {
      # Block known C2 domains, crypto miner callouts, tor exit nodes
      rules_string = <<-SURICATA
        drop tls $HOME_NET any -> $EXTERNAL_NET any (tls.sni; dotprefix; content:".onion"; nocase; msg:"TOR traffic detected"; sid:1000001; rev:1;)
        drop http $HOME_NET any -> $EXTERNAL_NET any (http.host; dotprefix; content:".onion"; nocase; msg:"TOR HTTP detected"; sid:1000002; rev:1;)
        drop dns $HOME_NET any -> any 53 (dns.query; dotprefix; content:".coin"; nocase; msg:"Cryptomining DNS query"; sid:1000003; rev:1;)
        alert http $EXTERNAL_NET any -> $HOME_NET any (http.method; content:"POST"; http.uri; content:"/wp-admin/"; nocase; msg:"WordPress admin POST from external"; flow:to_server; sid:1000004; rev:1;)
      SURICATA
    }
  }

  tags = local.common_tags
}

resource "aws_networkfirewall_firewall_policy" "this" {
  name = "central-egress-policy-${var.environment}"

  firewall_policy {
    stateless_default_actions          = ["aws:forward_to_sfe"]
    stateless_fragment_default_actions = ["aws:drop"]

    stateful_engine_options {
      rule_order = "STRICT_ORDER"
    }

    stateful_rule_group_reference {
      priority     = 100
      resource_arn = aws_networkfirewall_rule_group.threat_signatures.arn
    }

    stateful_rule_group_reference {
      priority     = 200
      resource_arn = aws_networkfirewall_rule_group.domain_allowlist.arn
    }
  }

  tags = local.common_tags
}

resource "aws_networkfirewall_firewall" "this" {
  name                = "central-firewall-${var.environment}"
  firewall_policy_arn = aws_networkfirewall_firewall_policy.this.arn
  vpc_id              = aws_vpc.inspection.id

  dynamic "subnet_mapping" {
    for_each = aws_subnet.firewall[*].id
    content {
      subnet_id = subnet_mapping.value
    }
  }

  tags = local.common_tags
}

resource "aws_networkfirewall_logging_configuration" "this" {
  firewall_arn = aws_networkfirewall_firewall.this.arn

  logging_configuration {
    log_destination_config {
      log_type             = "ALERT"
      log_destination_type = "CloudWatchLogs"
      log_destination = {
        logGroup = aws_cloudwatch_log_group.firewall_alert.name
      }
    }

    log_destination_config {
      log_type             = "FLOW"
      log_destination_type = "CloudWatchLogs"
      log_destination = {
        logGroup = aws_cloudwatch_log_group.firewall_flow.name
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "firewall_alert" {
  name              = "/aws/network-firewall/${var.environment}/alert"
  retention_in_days = 90
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "firewall_flow" {
  name              = "/aws/network-firewall/${var.environment}/flow"
  retention_in_days = 30
  tags              = local.common_tags
}

# ──────────────────────────────────────────────
# TGW Route Tables — isolate prod/dev, force via firewall
# ──────────────────────────────────────────────

resource "aws_ec2_transit_gateway_route_table" "spokes" {
  transit_gateway_id = aws_ec2_transit_gateway.this.id
  tags = merge(local.common_tags, { Name = "spokes-rt-${var.environment}" })
}

resource "aws_ec2_transit_gateway_route_table" "inspection" {
  transit_gateway_id = aws_ec2_transit_gateway.this.id
  tags = merge(local.common_tags, { Name = "inspection-rt-${var.environment}" })
}

# Default route in spoke RT → inspection VPC (all spoke traffic via firewall)
resource "aws_ec2_transit_gateway_route" "spoke_default" {
  destination_cidr_block         = "0.0.0.0/0"
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.spokes.id
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.inspection.id
}

# TGW attachment for inspection VPC itself
resource "aws_ec2_transit_gateway_vpc_attachment" "inspection" {
  transit_gateway_id = aws_ec2_transit_gateway.this.id
  vpc_id             = aws_vpc.inspection.id
  subnet_ids         = aws_subnet.tgw_attach[*].id

  tags = merge(local.common_tags, { Name = "inspection-vpc-tgw-attach-${var.environment}" })
}
