/**
 * Typed API client — calls the API Gateway directly (no BFF).
 *
 * Public routes (locations, leads) use VITE_API_KEY.
 * Authenticated routes use Bearer tokens from localStorage via auth.ts.
 * All functions throw an Error with a descriptive message on non-2xx responses.
 */

import type {
  AppEvent,
  AuthVerifyResponse,
  Contact,
  DocumentDetailResponse,
  DocumentsResponse,
  EventsDashboardResponse,
  EventsResponse,
  LeadsResponse,
  Link,
  LocationResponse,
  LocationsResponse,
  Property,
  ProspectSendResponse,
  ProspectSendResult,
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
    if (res.status === 401) {
      // Token is invalid or expired — clear it so ProtectedRoute redirects to login.
      clearToken()
    }
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
// Documents
// ---------------------------------------------------------------------------

export function getDocuments(
  locationPath: string,
  params: { from_date?: string; to_date?: string; limit?: number; last_key?: string } = {},
): Promise<DocumentsResponse> {
  return apiFetch(`/${locationPath}/documents`, { params })
}

/** @deprecated use getDocuments */
export function getLeads(
  locationPath: string,
  params: { from_date?: string; to_date?: string; limit?: number; last_key?: string } = {},
): Promise<DocumentsResponse> {
  return getDocuments(locationPath, params)
}

/** Fetch a single document with its contacts and properties. */
export function getDocument(documentId: string): Promise<DocumentDetailResponse> {
  return apiFetch(`/documents/${documentId}`)
}

export function parseDocument(documentId: string): Promise<DocumentDetailResponse> {
  return apiFetch(`/documents/${documentId}/parse-document`, { method: 'POST' })
}

/** Update mutable fields on a contact (role, name, email, dob, dod, address, notes). */
export async function updateContact(
  documentId: string,
  contactId: string,
  updates: Partial<Pick<Contact, 'role' | 'name' | 'email' | 'dob' | 'dod' | 'address' | 'notes'>>,
): Promise<{ contact: Contact }> {
  // API uses snake_case keys matching the DynamoDB attribute names
  return apiFetch(`/documents/${documentId}/contacts/${contactId}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  })
}

/** Delete a contact record. */
export async function deleteContact(
  documentId: string,
  contactId: string,
): Promise<{ deleted: string }> {
  return apiFetch(`/documents/${documentId}/contacts/${contactId}`, { method: 'DELETE' })
}

/** Update mutable fields on a property (address, legal_description, parcel_id, city, state, zip, notes). */
export async function updateProperty(
  documentId: string,
  propertyId: string,
  updates: Partial<Pick<Property, 'address' | 'legalDescription' | 'parcelId' | 'city' | 'state' | 'zip' | 'notes'>>,
): Promise<{ property: Property }> {
  // Map camelCase keys to the snake_case the API expects
  const body: Record<string, string | undefined> = {}
  if ('address'          in updates) body.address           = updates.address
  if ('legalDescription' in updates) body.legal_description = updates.legalDescription
  if ('parcelId'         in updates) body.parcel_id         = updates.parcelId
  if ('city'             in updates) body.city              = updates.city
  if ('state'            in updates) body.state             = updates.state
  if ('zip'              in updates) body.zip               = updates.zip
  if ('notes'            in updates) body.notes             = updates.notes
  return apiFetch(`/documents/${documentId}/properties/${propertyId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

/** Delete a property record. */
export async function deleteProperty(
  documentId: string,
  propertyId: string,
): Promise<{ deleted: string }> {
  return apiFetch(`/documents/${documentId}/properties/${propertyId}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Links
// ---------------------------------------------------------------------------

interface LinkBody {
  label?: string
  url: string
  link_type?: string
  notes?: string
}

/** Create a link attached to a contact or property. */
export function createLink(
  documentId: string,
  parentId: string,
  parentType: 'contact' | 'property',
  body: LinkBody,
): Promise<{ link: Link }> {
  const segment = parentType === 'contact' ? 'contacts' : 'properties'
  return apiFetch(`/documents/${documentId}/${segment}/${parentId}/links`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** Delete a link by id. */
export function deleteLink(
  documentId: string,
  parentId: string,
  parentType: 'contact' | 'property',
  linkId: string,
): Promise<{ deleted: string }> {
  const segment = parentType === 'contact' ? 'contacts' : 'properties'
  return apiFetch(`/documents/${documentId}/${segment}/${parentId}/links/${linkId}`, {
    method: 'DELETE',
  })
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
  update: {
    status?: string;
    role?: string;
    location_codes?: string[];
    journey_type?: string;
    journey_step?: string;
    trial_expires_on?: string;
  },
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
// Prospect
// ---------------------------------------------------------------------------

export async function adminSendProspect(
  emails: string[],
  leadCount: number,
  journeyType: string = 'prospect',
): Promise<ProspectSendResponse> {
  // For non-prospect journeys, use customer journey endpoints
  if (journeyType === 'coming_soon') {
    // Waitlist journey - uses bulk endpoint
    try {
      const response = await authedFetch('/journeys/invite-to-waitlist', {
        method: 'POST',
        body: JSON.stringify({
          emails: emails.map(e => e.trim())
        }),
      })
      return response as ProspectSendResponse
    } catch (error) {
      // If bulk call fails, return error for all emails
      const results: ProspectSendResult[] = emails.map(email => ({
        email,
        status: 'error',
        message: error instanceof Error ? error.message : 'Failed to send waitlist invitation'
      }))
      return { requestId: crypto.randomUUID(), results, count: results.length }
    }
  }

  if (journeyType === 'free_trial') {
    // Trial journey - uses bulk endpoint
    try {
      const response = await authedFetch('/journeys/invite-to-trial', {
        method: 'POST',
        body: JSON.stringify({
          emails: emails.map(e => e.trim()),
          trial_days: 14
        }),
      })
      return response as ProspectSendResponse
    } catch (error) {
      // If bulk call fails, return error for all emails
      const results: ProspectSendResult[] = emails.map(email => ({
        email,
        status: 'error',
        message: error instanceof Error ? error.message : 'Failed to send trial invitation'
      }))
      return { requestId: crypto.randomUUID(), results, count: results.length }
    }
  }

  // Default prospect journey - use existing bulk endpoint
  return authedFetch('/admin/prospect/send', {
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

// ---------------------------------------------------------------------------
// Admin event dashboard
// ---------------------------------------------------------------------------

export interface AdminEventsParams {
  user_id?:    string
  event_type?: string
  from_date?:  string
  to_date?:    string
  limit?:      number
}

export async function adminListAllEvents(params: AdminEventsParams = {}): Promise<EventsResponse> {
  return authedFetch('/admin/events', { params: params as Record<string, string | number | undefined> })
}

export async function adminGetEventsDashboard(weeks?: number): Promise<EventsDashboardResponse> {
  return authedFetch('/admin/events/dashboard', { params: weeks ? { weeks } : {} })
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export interface FeedbackBody {
  message: string
  source:  string
  email?:  string
}

/** Public endpoint — no API key or Bearer token required. */
export async function submitFeedback(body: FeedbackBody): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/feedback`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
  if (!res.ok) {
    const json = (await res.json().catch(() => ({}))) as { error?: string }
    throw new Error(json.error ?? 'Failed to submit feedback')
  }
  return res.json() as Promise<{ status: string }>
}
