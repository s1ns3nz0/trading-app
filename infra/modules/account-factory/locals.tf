locals {
  common_tags = {
    Company     = "TradingPlatform"
    Environment = var.environment
    Domain      = var.domain
    CostCenter  = var.cost_center
    Team        = var.team
    ManagedBy   = "terraform"
  }
}
