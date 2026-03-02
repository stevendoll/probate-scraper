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
  role: 'user' | 'admin'
  status: string
  locationCodes: string[]
  createdAt: string
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
