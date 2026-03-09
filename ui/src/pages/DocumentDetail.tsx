import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getDocument } from '@/lib/api'
import type { Contact, Property } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Field({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-40 shrink-0 text-muted-foreground">{label}</span>
      <span className="break-all">{value}</span>
    </div>
  )
}

function roleBadgeVariant(role: string): 'default' | 'secondary' | 'outline' {
  if (role === 'deceased') return 'default'
  if (role === 'executor') return 'secondary'
  return 'outline'
}

// ---------------------------------------------------------------------------
// Sub-sections
// ---------------------------------------------------------------------------

function ContactsSection({ contacts }: { contacts: Contact[] }) {
  if (contacts.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">People</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No contacts parsed yet.</p>
        </CardContent>
      </Card>
    )
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">People ({contacts.length})</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Role</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>DOB</TableHead>
                <TableHead>DOD</TableHead>
                <TableHead>Address</TableHead>
                <TableHead>Notes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {contacts.map((c) => (
                <TableRow key={c.contactId}>
                  <TableCell>
                    <Badge variant={roleBadgeVariant(c.role)} className="capitalize whitespace-nowrap">
                      {c.role}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-medium whitespace-nowrap">{c.name || '—'}</TableCell>
                  <TableCell className="whitespace-nowrap text-sm">{c.dob || '—'}</TableCell>
                  <TableCell className="whitespace-nowrap text-sm">{c.dod || '—'}</TableCell>
                  <TableCell className="text-sm max-w-[200px] truncate">{c.address || '—'}</TableCell>
                  <TableCell className="text-sm max-w-[160px] truncate text-muted-foreground">
                    {c.notes || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function PropertiesSection({ properties }: { properties: Property[] }) {
  if (properties.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Real Property</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No properties parsed yet.</p>
        </CardContent>
      </Card>
    )
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Real Property ({properties.length})</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Address</TableHead>
                <TableHead>City</TableHead>
                <TableHead>State</TableHead>
                <TableHead>ZIP</TableHead>
                <TableHead>Parcel ID</TableHead>
                <TableHead>Legal Description</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {properties.map((p) => (
                <TableRow key={p.propertyId}>
                  <TableCell className="font-medium">{p.address || '—'}</TableCell>
                  <TableCell>{p.city || '—'}</TableCell>
                  <TableCell>{p.state || '—'}</TableCell>
                  <TableCell>{p.zip || '—'}</TableCell>
                  <TableCell className="font-mono text-xs">{p.parcelId || '—'}</TableCell>
                  <TableCell className="text-sm max-w-[200px] truncate text-muted-foreground">
                    {p.legalDescription || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DocumentDetail() {
  const { documentId } = useParams<{ documentId: string }>()
  const navigate = useNavigate()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['documents', documentId],
    queryFn: () => getDocument(documentId!),
    enabled: !!documentId,
  })

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }

  if (isError || !data) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          ← Back
        </Button>
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : 'Failed to load document'}
        </p>
      </div>
    )
  }

  const doc = data.document

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          ← Back
        </Button>
        <div>
          <h1 className="text-2xl font-semibold">Document {doc.docNumber}</h1>
          <p className="text-sm text-muted-foreground">{doc.locationCode} · {doc.recordedDate}</p>
        </div>
      </div>

      {/* Document fields */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Filing details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Field label="Doc number"       value={doc.docNumber} />
          <Field label="Recorded date"    value={doc.recordedDate} />
          <Field label="Grantor"          value={doc.grantor} />
          <Field label="Grantee"          value={doc.grantee} />
          <Field label="Document type"    value={doc.docType} />
          <Field label="County"           value={doc.locationCode} />
          <Field label="Book/Vol/Page"    value={doc.bookVolumePage} />
          <Field label="Record number"    value={doc.recordNumber} />
          <Field label="Page number"      value={doc.pageNumber} />
          <Field label="Legal description" value={doc.legalDescription} />
          {doc.pdfUrl && (
            <div className="flex gap-2 text-sm pt-1">
              <span className="w-40 shrink-0 text-muted-foreground">PDF</span>
              <a
                href={doc.pdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline-offset-2 hover:underline"
              >
                View PDF ↗
              </a>
            </div>
          )}
          <Field label="Extracted at"  value={doc.extractedAt} />
          <Field label="Processed at"  value={doc.processedAt} />
        </CardContent>
      </Card>

      {/* Contacts */}
      <ContactsSection contacts={data.contacts} />

      {/* Properties */}
      <PropertiesSection properties={data.properties} />
    </div>
  )
}
