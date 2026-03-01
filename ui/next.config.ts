import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Allow the Next.js API routes to call the API Gateway without CORS issues
  async rewrites() {
    return []
  },
  // Strict mode catches common React bugs early
  reactStrictMode: true,
}

export default nextConfig
