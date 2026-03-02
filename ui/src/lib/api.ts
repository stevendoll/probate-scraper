/**
 * Typed API client — calls the API Gateway directly (no Next.js BFF).
 *
 * Public routes (locations, leads) use VITE_API_KEY.
 * Authenticated routes use Bearer tokens from localStorage via auth.ts.
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
import { getToken, clearToken } from './auth'

const BASE = import.meta.env.VITE_API_URL ?? ''
const API_KEY = import.meta.env.VITE_API_KEY ?? ''

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
    } catch { /* ignore */ }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

async function authedFetch<T>(
  path: string,
  options: RequestInit & { params?: Record<string, string | number | undefined> } = {},
): Promise<T> {
  const token = getToken()
  if (!token) throw new Error('Not authenticated')
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
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      message = body.error ?? body.message ?? message
    } catch { /* ignore */ }
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
  params: { from_date?: string; to_date?: string; limit?: number; last_key?: string } = {},
): Promise<LeadsResponse> {
  return apiFetch(`/${locationPath}/leads`, { params })
}

// ---------------------------------------------------------------------------
// Auth (calls API Gateway directly — no API key required on these routes)
// ---------------------------------------------------------------------------

export async function requestLogin(email: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/request-login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { error?: string }).error ?? 'Failed to send magic link')
  }
}

export async function verifyMagicToken(token: string): Promise<AuthVerifyResponse> {
  const res = await fetch(`${BASE}/auth/verify?token=${encodeURIComponent(token)}`)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { error?: string }).error ?? 'Invalid or expired link')
  }
  return res.json() as Promise<AuthVerifyResponse>
}

export async function getMe(): Promise<User> {
  const data = await authedFetch<{ user: User }>('/auth/me')
  return data.user
}

export async function patchMe(update: { email: string }): Promise<User> {
  const data = await authedFetch<{ user: User }>('/auth/me', {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
  return data.user
}

export async function getMyLeads(
  params: { from_date?: string; to_date?: string } = {},
): Promise<LeadsResponse> {
  return authedFetch('/auth/leads', { params })
}

export function logout(): void {
  clearToken()
}

// ---------------------------------------------------------------------------
// Admin (Bearer token required, no API key)
// ---------------------------------------------------------------------------

export async function adminListUsers(): Promise<UsersResponse> {
  return authedFetch('/admin/users')
}

export async function adminGetUser(userId: string): Promise<UserResponse> {
  return authedFetch(`/admin/users/${userId}`)
}

export async function adminPatchUser(
  userId: string,
  update: { status?: string; role?: string; location_codes?: string[] },
): Promise<UserResponse> {
  return authedFetch(`/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
}

export async function adminDeleteUser(userId: string): Promise<UserResponse> {
  return authedFetch(`/admin/users/${userId}`, { method: 'DELETE' })
}
