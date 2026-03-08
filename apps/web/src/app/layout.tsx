import type { Metadata } from 'next'
import './globals.css'
import { Providers } from './providers'

export const metadata: Metadata = {
  title: { template: '%s | CryptoTrade', default: 'CryptoTrade' },
  description: 'Professional crypto trading platform',
  robots: { index: false, follow: false }, // private trading app
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full bg-bg-primary">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
