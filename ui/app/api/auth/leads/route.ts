import { NextRequest, NextResponse } from 'next/server'
import { ACCESS_TOKEN_COOKIE } from '@/lib/auth'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

export async function GET(req: NextRequest) {
  const token = req.cookies.get(ACCESS_TOKEN_COOKIE)?.value
  if (!token) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })

  const { searchParams } = req.nextUrl
  const qs = new URLSearchParams()
  if (searchParams.get('from_date')) qs.set('from_date', searchParams.get('from_date')!)
  if (searchParams.get('to_date')) qs.set('to_date', searchParams.get('to_date')!)

  const upstream = await fetch(`${API_BASE}/auth/leads?${qs}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const data = await upstream.json().catch(() => ({}))
  return NextResponse.json(data, { status: upstream.status })
}
