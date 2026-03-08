import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: '#0b0e11',
          secondary: '#161a1e',
          tertiary: '#1e2329',
        },
        border: {
          DEFAULT: '#2b3139',
          light: '#3d4555',
        },
        text: {
          primary: '#eaecef',
          secondary: '#848e9c',
          muted: '#5e6673',
        },
        up: '#02c076',
        down: '#f6465d',
        accent: '#f0b90b',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
}

export default config
