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
  documentId?: string
  docNumber: string
  recordedDate: string
  grantor: string
  grantee: string
  locationCode: string
  // Full document fields (present when fetched via GET /documents/{id})
  docType?: string
  bookVolumePage?: string
  legalDescription?: string
  recordNumber?: string
  pageNumber?: string
  extractedAt?: string
  processedAt?: string
  scrapeRunId?: string
  offset?: string
  docS3Uri?: string
  docLocalPath?: string
  pdfUrl?: string
  parsedAt?: string
  deceasedName?: string
}

/** Response from GET /{location_path}/documents */
export interface DocumentsResponse {
  documents: Lead[]
  location: Location
  count: number
  query: Record<string, string>
  nextKey?: string
}

/** @deprecated use DocumentsResponse */
export interface LeadsResponse {
  leads: Lead[]
  count: number
  nextKey?: string
}

export interface Contact {
  contactId: string
  documentId: string
  role: string
  name: string
  email?: string
  dob?: string
  dod?: string
  address?: string
  notes?: string
  parsedAt?: string
  parsedModel?: string
  rawResponse?: string
}

export interface Property {
  propertyId: string
  documentId: string
  address?: string
  legalDescription?: string
  parcelId?: string
  city?: string
  state?: string
  zip?: string
  notes?: string
  isVerified?: boolean
  parsedAt?: string
  parsedModel?: string
  rawResponse?: string
}

/** Response from GET /documents/{document_id} */
export interface DocumentDetailResponse {
  requestId: string
  document: Lead
  contacts: Contact[]
  properties: Property[]
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
