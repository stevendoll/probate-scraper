export interface Location {
  locationCode: string
  locationPath: string
  locationName: string
  searchUrl: string
  retrievedAt?: string
}

export interface LocationsResponse {
  locations: Location[]
}

export interface LocationResponse {
  location: Location
}

export interface Lead {
  leadId?: string
  docNumber: string
  recordedDate: string
  grantor: string
  grantee: string
  locationCode: string
  pdfUrl?: string
  parsedAt?: string
  deceasedName?: string
}

export interface LeadsResponse {
  leads: Lead[]
  count: number
  nextKey?: string
}

export interface User {
  userId: string
  email: string
  firstName: string
  lastName: string
  role: 'user' | 'admin'
  status: string
  locationCodes: string[]
  offeredPrice?: number
  createdAt: string
}

export interface ProspectSendResult {
  email: string
  status: 'sent' | 'skipped' | 'error'
  userId?: string
  price?: number
  message?: string
}

export interface ProspectSendResponse {
  requestId: string
  results: ProspectSendResult[]
  count: number
}

export interface UserResponse {
  user: User
}

export interface UsersResponse {
  users: User[]
}

export interface AuthVerifyResponse {
  accessToken: string
  user: User
}
