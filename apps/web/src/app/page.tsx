import { redirect } from 'next/navigation'

// Root redirects to default spot trading pair
export default function HomePage() {
  redirect('/spot/BTC-USDT')
}
