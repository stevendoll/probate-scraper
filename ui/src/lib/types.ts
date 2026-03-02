// ---------------------------------------------------------------------------
// Domain types — mirror the Python models in src/api/models.py
// ---------------------------------------------------------------------------

export interface Location {
  locationCode: string
  locationPath: string
  locationName: string
  searchUrl: string
  retrievedAt: string
}

export interface Lead {
  leadId: string
  docNumber: string
  grantor: string
  grantee: string
  docType: string
  recordedDate: string        // YYYY-MM-DD
  bookVolumePage: string
  legalDescription: string
  locationCode: string
  pdfUrl: string
  docS3Uri: string
  extractedAt: string
  // Parsed fields (populated by Bedrock)
  parsedAt?: string
  parsedModel?: string
  deceasedName?: string
  deceasedDob?: string
  deceasedDod?: string
  deceasedLastAddress?: string
  people?: unknown[]
  realProperty?: unknown[]
  summary?: string
  parseError?: string
}

export interface User {
  userId: string
  email: string
  role: 'user' | 'admin'
  status: 'active' | 'inactive' | 'canceled' | 'past_due' | 'trialing'
  locationCodes: string[]
  stripeCustomerId: string
  stripeSubscriptionId: string
  createdAt: string
  updatedAt: string
}

// ---------------------------------------------------------------------------
// API response envelopes
// ---------------------------------------------------------------------------

export interface LeadsResponse {
  leads: Lead[]
  location: Location
  count: number
  query: Record<string, string>
  nextKey?: string
}

export interface LocationsResponse {
  locations: Location[]
  count: number
}

export interface LocationResponse {
  location: Location
}

export interface UsersResponse {
  users: User[]
  count: number
}

export interface UserResponse {
  user: User
  requestId: string
}

export interface AuthVerifyResponse {
  accessToken: string
  user: User
}

// ---------------------------------------------------------------------------
// Misc
// ---------------------------------------------------------------------------

export type UserStatus = User['status']
export type UserRole = User['role']
