/**
 * GET /api/auth/verify?token=...
 *
 * Exchanges the magic-link token for an access token, then stores the
 * access token in an httpOnly cookie so the browser never sees the raw JWT.
 */
import { NextRequest, NextResponse } from 'next/server'
import { ACCESS_TOKEN_COOKIE } from '@/lib/auth'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

// 7 days in seconds — matches the API's ACCESS_TOKEN_EXPIRY_DAYS
const COOKIE_MAX_AGE = 7 * 24 * 60 * 60

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get('token')
  if (!token) {
    return NextResponse.json({ error: 'Missing token' }, { status: 400 })
  }

  const upstream = await fetch(
    `${API_BASE}/auth/verify?token=${encodeURIComponent(token)}`,
    { cache: 'no-store' },
  )

  if (!upstream.ok) {
    const data = await upstream.json().catch(() => ({}))
    return NextResponse.json(
      { error: data.error ?? 'Invalid or expired link' },
      { status: upstream.status },
    )
  }

  const { accessToken, user } = await upstream.json()

  const res = NextResponse.json({ user })
  res.cookies.set(ACCESS_TOKEN_COOKIE, accessToken, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: COOKIE_MAX_AGE,
    path: '/',
  })
  return res
}
