import { NextRequest, NextResponse } from 'next/server'
import { ACCESS_TOKEN_COOKIE } from '@/lib/auth'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

type Params = { params: Promise<{ userId: string }> }

export async function GET(req: NextRequest, { params }: Params) {
  const { userId } = await params
  const token = req.cookies.get(ACCESS_TOKEN_COOKIE)?.value
  if (!token) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })

  const upstream = await fetch(`${API_BASE}/admin/users/${userId}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const data = await upstream.json().catch(() => ({}))
  return NextResponse.json(data, { status: upstream.status })
}

export async function PATCH(req: NextRequest, { params }: Params) {
  const { userId } = await params
  const token = req.cookies.get(ACCESS_TOKEN_COOKIE)?.value
  if (!token) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })

  const body = await req.json().catch(() => ({}))
  const upstream = await fetch(`${API_BASE}/admin/users/${userId}`, {
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

export async function DELETE(req: NextRequest, { params }: Params) {
  const { userId } = await params
  const token = req.cookies.get(ACCESS_TOKEN_COOKIE)?.value
  if (!token) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })

  const upstream = await fetch(`${API_BASE}/admin/users/${userId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  const data = await upstream.json().catch(() => ({}))
  return NextResponse.json(data, { status: upstream.status })
}
