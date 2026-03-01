/**
 * Typed API client.
 *
 * Public routes (locations, leads) use NEXT_PUBLIC_API_KEY.
 * Auth routes use Bearer tokens stored in the httpOnly cookie, forwarded
 * from the browser via the Next.js /api/auth/* proxy routes.
 *
 * All functions throw an Error with a descriptive message on non-2xx responses.
 */

import type {
  AuthVerifyResponse,
  LeadsResponse,
  LocationResponse,
  LocationsResponse,
  User,
  UserResponse,
  UsersResponse,
} from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL ?? ''
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? ''

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  options: RequestInit & { params?: Record<string, string | number | undefined> } = {},
): Promise<T> {
  const { params, ...init } = options

  const url = new URL(`${BASE}${path}`)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
    })
  }

  const res = await fetch(url.toString(), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': API_KEY,
      ...init.headers,
    },
  })

  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      message = body.error ?? body.message ?? message
    } catch {
      // ignore
    }
    throw new Error(message)
  }

  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Locations
// ---------------------------------------------------------------------------

export function getLocations(): Promise<LocationsResponse> {
  return apiFetch('/locations')
}

export function getLocation(locationCode: string): Promise<LocationResponse> {
  return apiFetch(`/locations/${locationCode}`)
}

// ---------------------------------------------------------------------------
// Leads
// ---------------------------------------------------------------------------

export function getLeads(
  locationPath: string,
  params: {
    from_date?: string
    to_date?: string
    limit?: number
    last_key?: string
  } = {},
): Promise<LeadsResponse> {
  return apiFetch(`/${locationPath}/leads`, { params })
}

// ---------------------------------------------------------------------------
// Auth  (calls Next.js /api/auth/* proxy routes, not the API Gateway directly)
// ---------------------------------------------------------------------------

export async function requestLogin(email: string): Promise<void> {
  const res = await fetch('/api/auth/request-login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Failed to send magic link')
  }
}

export async function verifyMagicToken(token: string): Promise<AuthVerifyResponse> {
  const res = await fetch(`/api/auth/verify?token=${encodeURIComponent(token)}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Invalid or expired link')
  }
  return res.json()
}

export async function getMe(): Promise<User> {
  const res = await fetch('/api/auth/me')
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Not authenticated')
  }
  const data = await res.json()
  return data.user ?? data
}

export async function patchMe(update: { email: string }): Promise<User> {
  const res = await fetch('/api/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Failed to update profile')
  }
  const data = await res.json()
  return data.user ?? data
}

export async function getMyLeads(params: {
  from_date?: string
  to_date?: string
} = {}): Promise<LeadsResponse> {
  const qs = new URLSearchParams()
  if (params.from_date) qs.set('from_date', params.from_date)
  if (params.to_date) qs.set('to_date', params.to_date)
  const res = await fetch(`/api/auth/leads?${qs.toString()}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Failed to load leads')
  }
  return res.json()
}

export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST' })
}

// ---------------------------------------------------------------------------
// Admin  (calls Next.js /api/admin/* proxy routes)
// ---------------------------------------------------------------------------

export async function adminListUsers(): Promise<UsersResponse> {
  const res = await fetch('/api/admin/users')
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Forbidden')
  }
  return res.json()
}

export async function adminGetUser(userId: string): Promise<UserResponse> {
  const res = await fetch(`/api/admin/users/${userId}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Not found')
  }
  return res.json()
}

export async function adminPatchUser(
  userId: string,
  update: { status?: string; role?: string; location_codes?: string[] },
): Promise<UserResponse> {
  const res = await fetch(`/api/admin/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Failed to update user')
  }
  return res.json()
}

export async function adminDeleteUser(userId: string): Promise<UserResponse> {
  const res = await fetch(`/api/admin/users/${userId}`, { method: 'DELETE' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error ?? 'Failed to delete user')
  }
  return res.json()
}
