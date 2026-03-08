locals {
  common_tags = {
    Company    = "TradingPlatform"
    Environment = var.environment
    Domain     = "Network"
    CostCenter = "CC-NETWORK"
    Team       = "infra"
    ManagedBy  = "terraform"
  }
}
