/**
 * Typed API client — calls the API Gateway directly (no BFF).
 *
 * Public routes (locations, leads) use VITE_API_KEY.
 * Authenticated routes use Bearer tokens from localStorage via auth.ts.
 * All functions throw an Error with a descriptive message on non-2xx responses.
 */

import type {
  AuthVerifyResponse,
  FunnelSendResponse,
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

type Params = Record<string, string | number | undefined>

async function apiFetch<T>(path: string, options: RequestInit & { params?: Params } = {}): Promise<T> {
  const { params, ...init } = options
  const url = new URL(`${BASE}${path}`)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
    }
  }
  const res = await fetch(url.toString(), {
    ...init,
    headers: { 'Content-Type': 'application/json', 'x-api-key': API_KEY, ...init.headers },
  })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { error?: string; message?: string }
      message = body.error ?? body.message ?? message
    } catch { /* ignore */ }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

async function authedFetch<T>(path: string, options: RequestInit & { params?: Params } = {}): Promise<T> {
  const token = getToken()
  if (!token) throw new Error('Not authenticated')
  const { params, ...init } = options
  const url = new URL(`${BASE}${path}`)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
    }
  }
  const res = await fetch(url.toString(), {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init.headers },
  })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { error?: string; message?: string }
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
// Auth
// ---------------------------------------------------------------------------

export async function requestLogin(email: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/request-login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(body.error ?? 'Failed to send magic link')
  }
}

export async function verifyMagicToken(token: string): Promise<AuthVerifyResponse> {
  const res = await fetch(`${BASE}/auth/verify?token=${encodeURIComponent(token)}`)
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(body.error ?? 'Invalid or expired link')
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
// Admin
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

// ---------------------------------------------------------------------------
// Funnel
// ---------------------------------------------------------------------------

export async function adminSendFunnel(
  emails: string[],
  leadCount: number,
): Promise<FunnelSendResponse> {
  return authedFetch('/admin/funnel/send', {
    method: 'POST',
    body: JSON.stringify({ emails, lead_count: leadCount }),
  })
}

/** Called from the public /unsubscribe page — no API key or Bearer needed. */
export async function unsubscribe(token: string): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/auth/unsubscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(body.error ?? 'Failed to unsubscribe')
  }
  return res.json() as Promise<{ message: string }>
}

/** Called from the public /signup page — no API key or Bearer needed. */
export async function createCheckoutSession(token: string): Promise<{ url: string }> {
  const res = await fetch(`${BASE}/stripe/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(body.error ?? 'Failed to start checkout')
  }
  return res.json() as Promise<{ url: string }>
}
