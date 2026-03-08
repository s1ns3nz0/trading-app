// ─── Common ───────────────────────────────────────────────────────────────────

export type Side = 'buy' | 'sell'
export type OrderType = 'market' | 'limit' | 'stop_limit'
export type OrderStatus = 'open' | 'partial' | 'filled' | 'cancelled'
export type TimeInForce = 'GTC' | 'IOC' | 'FOK'

// ─── Market Data ──────────────────────────────────────────────────────────────

export interface Ticker {
  symbol: string
  lastPrice: string
  priceChange: string
  priceChangePercent: string
  high24h: string
  low24h: string
  volume24h: string
  quoteVolume24h: string
  timestamp: number
}

export interface OrderBookLevel {
  price: string
  size: string
  total: string // cumulative size
}

export interface OrderBook {
  symbol: string
  bids: OrderBookLevel[]
  asks: OrderBookLevel[]
  lastUpdateId: number
  timestamp: number
}

export interface Trade {
  id: string
  symbol: string
  price: string
  size: string
  side: Side
  timestamp: number
}

export interface Candle {
  openTime: number
  open: string
  high: string
  low: string
  close: string
  volume: string
  closeTime: number
}

// ─── Orders ───────────────────────────────────────────────────────────────────

export interface Order {
  id: string
  clientOrderId?: string
  symbol: string
  type: OrderType
  side: Side
  status: OrderStatus
  price?: string
  stopPrice?: string
  quantity: string
  filledQuantity: string
  avgFillPrice?: string
  timeInForce: TimeInForce
  createdAt: number
  updatedAt: number
}

export interface PlaceOrderRequest {
  symbol: string
  type: OrderType
  side: Side
  quantity: string
  price?: string
  stopPrice?: string
  timeInForce?: TimeInForce
  clientOrderId?: string
}

// ─── Futures ──────────────────────────────────────────────────────────────────

export type MarginMode = 'cross' | 'isolated'
export type PositionSide = 'long' | 'short'

export interface FuturesPosition {
  id: string
  symbol: string
  side: PositionSide
  leverage: number
  marginMode: MarginMode
  entryPrice: string
  markPrice: string
  liquidationPrice: string
  size: string
  unrealizedPnl: string
  realizedPnl: string
  margin: string
  marginRatio: string
  createdAt: number
}

export interface FuturesOrderRequest extends PlaceOrderRequest {
  leverage?: number
  marginMode?: MarginMode
  reduceOnly?: boolean
  positionSide?: PositionSide
}

export interface FuturesAccountInfo {
  totalMarginBalance: string
  availableMargin: string
  unrealizedPnl: string
  totalWalletBalance: string
  leverage: number
  marginMode: MarginMode
}

// ─── Portfolio / Balance ──────────────────────────────────────────────────────

export interface AssetBalance {
  asset: string
  free: string
  locked: string
  total: string
  usdtValue: string
}

export interface Portfolio {
  totalValueUsdt: string
  availableUsdt: string
  balances: AssetBalance[]
  pnl24h: string
  pnl24hPercent: string
}

// ─── Auth / Identity ─────────────────────────────────────────────────────────

export type KycStatus = 'pending' | 'submitted' | 'approved' | 'rejected'

export interface User {
  id: string
  email: string
  username: string
  kycStatus: KycStatus
  twoFactorEnabled: boolean
  createdAt: number
}

export interface AuthTokens {
  accessToken: string
  refreshToken: string
  expiresIn: number
}

export interface LoginRequest {
  email: string
  password: string
  totpCode?: string
}

export interface RegisterRequest {
  email: string
  username: string
  password: string
}

// ─── Finance ─────────────────────────────────────────────────────────────────

export type DepositStatus = 'pending' | 'confirming' | 'confirmed' | 'failed'
export type WithdrawalStatus = 'pending' | 'processing' | 'completed' | 'rejected'

export interface Network {
  id: string
  name: string
  minDeposit: string
  minWithdrawal: string
  withdrawalFee: string
  confirmations: number
  estimatedArrival: string
}

export interface DepositAddress {
  asset: string
  network: string
  address: string
  tag?: string
}

export interface DepositRecord {
  id: string
  asset: string
  network: string
  amount: string
  status: DepositStatus
  txHash?: string
  confirmations: number
  requiredConfirmations: number
  createdAt: number
  completedAt?: number
}

export interface WithdrawalRequest {
  asset: string
  network: string
  address: string
  tag?: string
  amount: string
}

export interface WithdrawalRecord {
  id: string
  asset: string
  network: string
  address: string
  amount: string
  fee: string
  status: WithdrawalStatus
  txHash?: string
  createdAt: number
  completedAt?: number
}

// ─── WebSocket message types ──────────────────────────────────────────────────

export interface WsTickerMessage {
  type: 'ticker'
  data: Ticker
}

export interface WsOrderBookMessage {
  type: 'orderbook'
  data: OrderBook
}

export interface WsTradeMessage {
  type: 'trade'
  data: Trade
}

export interface WsOrderUpdateMessage {
  type: 'order_update'
  data: Order
}

export type WsMessage =
  | WsTickerMessage
  | WsOrderBookMessage
  | WsTradeMessage
  | WsOrderUpdateMessage
