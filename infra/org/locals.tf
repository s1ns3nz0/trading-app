locals {
  domain_cost_centers = {
    SpotTrading     = "CC-SPOT"
    FuturesTrading  = "CC-FUTURES"
    Deposit         = "CC-DEPOSIT"
    Withdrawal      = "CC-WITHDRAW"
    Identity        = "CC-IDENTITY"
    MarketData      = "CC-MARKET"
    Notification    = "CC-NOTIFY"
    RiskCompliance  = "CC-RISK"
    Security        = "CC-SECURITY"
    Network         = "CC-NETWORK"
    Shared          = "CC-SHARED"
  }
}
