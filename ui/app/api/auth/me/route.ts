import { NextRequest, NextResponse } from 'next/server'
import { ACCESS_TOKEN_COOKIE } from '@/lib/auth'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

async function bearer(req: NextRequest) {
  return req.cookies.get(ACCESS_TOKEN_COOKIE)?.value ?? null
}

export async function GET(req: NextRequest) {
  const token = await bearer(req)
  if (!token) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })

  const upstream = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const data = await upstream.json().catch(() => ({}))
  return NextResponse.json(data, { status: upstream.status })
}

export async function PATCH(req: NextRequest) {
  const token = await bearer(req)
  if (!token) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })

  const body = await req.json().catch(() => ({}))
  const upstream = await fetch(`${API_BASE}/auth/me`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  })
  const data = await upstream.json().catch(() => ({}))
  return NextResponse.json(data, { status: upstream.status })
}
