import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // radix-ui (used by shadcn v3) ships ESM-only code that Next.js's bundler
  // needs to transpile explicitly; without this you get:
  //   TypeError: Class extends value #<Object> is not a constructor or null
  transpilePackages: ['radix-ui'],
}

export default nextConfig
