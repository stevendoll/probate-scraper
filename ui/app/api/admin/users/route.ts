import { NextRequest, NextResponse } from 'next/server'
import { ACCESS_TOKEN_COOKIE } from '@/lib/auth'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

export async function GET(req: NextRequest) {
  const token = req.cookies.get(ACCESS_TOKEN_COOKIE)?.value
  if (!token) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })

  const upstream = await fetch(`${API_BASE}/admin/users`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const data = await upstream.json().catch(() => ({}))
  return NextResponse.json(data, { status: upstream.status })
}
