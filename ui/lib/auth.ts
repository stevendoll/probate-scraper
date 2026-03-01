/**
 * Auth helpers for server components / API routes.
 *
 * The access token lives in an httpOnly cookie named `access_token`.
 * Server components read it via next/headers; the browser never sees it.
 */

import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import type { User } from './types'

export const ACCESS_TOKEN_COOKIE = 'access_token'

// ---------------------------------------------------------------------------
// Cookie helpers (server-side only)
// ---------------------------------------------------------------------------

/** Read the raw access token from the httpOnly cookie. Returns null if missing. */
export async function getAccessToken(): Promise<string | null> {
  const jar = await cookies()
  return jar.get(ACCESS_TOKEN_COOKIE)?.value ?? null
}

/**
 * Decode the JWT payload without verifying the signature.
 * Verification happens on the API side; here we just need the claims
 * (role, exp) to make routing decisions quickly.
 */
export function decodePayload(token: string): Record<string, unknown> | null {
  try {
    const [, payloadB64] = token.split('.')
    const json = Buffer.from(payloadB64, 'base64url').toString('utf8')
    return JSON.parse(json) as Record<string, unknown>
  } catch {
    return null
  }
}

/** True when the token's `exp` is still in the future. */
export function isTokenExpired(token: string): boolean {
  const payload = decodePayload(token)
  if (!payload || typeof payload.exp !== 'number') return true
  return Date.now() / 1000 >= payload.exp
}

// ---------------------------------------------------------------------------
// Route guards (for use in server components / layouts)
// ---------------------------------------------------------------------------

/**
 * Require an authenticated user.
 * Redirects to /login if no valid token exists.
 */
export async function requireAuth(): Promise<{ token: string; payload: Record<string, unknown> }> {
  const token = await getAccessToken()
  if (!token || isTokenExpired(token)) {
    redirect('/login')
  }
  const payload = decodePayload(token)!
  return { token, payload }
}

/**
 * Require an admin user.
 * Redirects to /dashboard if the user doesn't have the admin role.
 */
export async function requireAdmin(): Promise<{ token: string; payload: Record<string, unknown> }> {
  const { token, payload } = await requireAuth()
  if (payload.role !== 'admin') {
    redirect('/dashboard')
  }
  return { token, payload }
}

// ---------------------------------------------------------------------------
// API calls authenticated as the current user (server-side)
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

async function authedFetch(
  token: string,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
    cache: 'no-store',
  })
}

/** Fetch the current user's profile from the API. */
export async function fetchMe(token: string): Promise<User> {
  const res = await authedFetch(token, '/auth/me')
  if (!res.ok) throw new Error(`fetchMe failed: ${res.status}`)
  const data = await res.json()
  return (data.user ?? data) as User
}
