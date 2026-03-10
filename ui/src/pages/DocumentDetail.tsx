import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDocument, updateContact, deleteContact, updateProperty, deleteProperty } from '@/lib/api'
import type { Contact, Property } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Field({ label, value }: { label: string; value?: string | number | null }) {
  if (value === undefined || value === null || value === '' || value === 0) return null
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-40 shrink-0 text-muted-foreground">{label}</span>
      <span className="break-all">{String(value)}</span>
    </div>
  )
}

function roleBadgeVariant(role: string): 'default' | 'secondary' | 'outline' {
  if (role === 'deceased') return 'default'
  if (role === 'executor') return 'secondary'
  return 'outline'
}

// ---------------------------------------------------------------------------
// Contact edit dialog
// ---------------------------------------------------------------------------

interface ContactFormState {
  role: string
  name: string
  email: string
  dob: string
  dod: string
  address: string
  notes: string
}

function EditContactDialog({
  documentId,
  contact,
  open,
  onOpenChange,
}: {
  documentId: string
  contact: Contact
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState<ContactFormState>({
    role:    contact.role    ?? '',
    name:    contact.name    ?? '',
    email:   contact.email   ?? '',
    dob:     contact.dob     ?? '',
    dod:     contact.dod     ?? '',
    address: contact.address ?? '',
    notes:   contact.notes   ?? '',
  })

  const mut = useMutation({
    mutationFn: () => updateContact(documentId, contact.contactId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents', documentId] })
      onOpenChange(false)
    },
  })

  const field = (key: keyof ContactFormState, label: string, placeholder?: string) => (
    <div className="grid grid-cols-4 items-center gap-4" key={key}>
      <Label className="text-right">{label}</Label>
      <Input
        className="col-span-3"
        placeholder={placeholder}
        value={form[key]}
        onChange={e => setForm(prev => ({ ...prev, [key]: e.target.value }))}
      />
    </div>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit contact</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          {field('name',    'Name')}
          {field('role',    'Role',    'e.g. executor, heir, beneficiary')}
          {field('email',   'Email')}
          {field('dob',     'DOB',     'YYYY-MM-DD')}
          {field('dod',     'DOD',     'YYYY-MM-DD')}
          {field('address', 'Address')}
          {field('notes',   'Notes')}
        </div>
        {mut.isError && (
          <p className="text-sm text-destructive px-1">
            {mut.error instanceof Error ? mut.error.message : 'Save failed'}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => mut.mutate()} disabled={mut.isPending}>
            {mut.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Property edit dialog
// ---------------------------------------------------------------------------

interface PropertyFormState {
  address: string
  legalDescription: string
  parcelId: string
  city: string
  state: string
  zip: string
  notes: string
}

function EditPropertyDialog({
  documentId,
  property,
  open,
  onOpenChange,
}: {
  documentId: string
  property: Property
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState<PropertyFormState>({
    address:          property.address          ?? '',
    legalDescription: property.legalDescription ?? '',
    parcelId:         property.parcelId         ?? '',
    city:             property.city             ?? '',
    state:            property.state            ?? '',
    zip:              property.zip              ?? '',
    notes:            property.notes            ?? '',
  })

  const mut = useMutation({
    mutationFn: () => updateProperty(documentId, property.propertyId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents', documentId] })
      onOpenChange(false)
    },
  })

  const field = (key: keyof PropertyFormState, label: string, placeholder?: string) => (
    <div className="grid grid-cols-4 items-center gap-4" key={key}>
      <Label className="text-right">{label}</Label>
      <Input
        className="col-span-3"
        placeholder={placeholder}
        value={form[key]}
        onChange={e => setForm(prev => ({ ...prev, [key]: e.target.value }))}
      />
    </div>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit property</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          {field('address',          'Address')}
          {field('legalDescription', 'Legal description')}
          {field('parcelId',         'Parcel ID')}
          {field('city',             'City')}
          {field('state',            'State',  'e.g. TX')}
          {field('zip',              'ZIP')}
          {field('notes',            'Notes')}
        </div>
        {mut.isError && (
          <p className="text-sm text-destructive px-1">
            {mut.error instanceof Error ? mut.error.message : 'Save failed'}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => mut.mutate()} disabled={mut.isPending}>
            {mut.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Contacts section
// ---------------------------------------------------------------------------

function ContactRow({
  documentId,
  contact,
  onDelete,
}: {
  documentId: string
  contact: Contact
  onDelete: (id: string) => void
}) {
  const [editOpen, setEditOpen] = useState(false)

  return (
    <>
      <TableRow>
        <TableCell>
          <Badge variant={roleBadgeVariant(contact.role)} className="capitalize whitespace-nowrap">
            {contact.role}
          </Badge>
        </TableCell>
        <TableCell className="font-medium whitespace-nowrap">{contact.name || '—'}</TableCell>
        <TableCell className="text-sm">{contact.email || '—'}</TableCell>
        <TableCell className="whitespace-nowrap text-sm">{contact.dob || '—'}</TableCell>
        <TableCell className="whitespace-nowrap text-sm">{contact.dod || '—'}</TableCell>
        <TableCell className="text-sm max-w-[200px] truncate">{contact.address || '—'}</TableCell>
        <TableCell className="text-sm max-w-[160px] truncate text-muted-foreground">
          {contact.notes || '—'}
        </TableCell>
        <TableCell>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={() => setEditOpen(true)}>Edit</Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => onDelete(contact.contactId)}
            >
              Delete
            </Button>
          </div>
        </TableCell>
      </TableRow>
      {editOpen && (
        <EditContactDialog
          documentId={documentId}
          contact={contact}
          open={editOpen}
          onOpenChange={setEditOpen}
        />
      )}
    </>
  )
}

function ContactsSection({
  documentId,
  contacts,
}: {
  documentId: string
  contacts: Contact[]
}) {
  const qc = useQueryClient()
  const deleteMut = useMutation({
    mutationFn: (contactId: string) => deleteContact(documentId, contactId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents', documentId] }),
  })

  if (contacts.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">People</CardTitle></CardHeader>
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
                <TableHead>Email</TableHead>
                <TableHead>DOB</TableHead>
                <TableHead>DOD</TableHead>
                <TableHead>Address</TableHead>
                <TableHead>Notes</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {contacts.map(c => (
                <ContactRow
                  key={c.contactId}
                  documentId={documentId}
                  contact={c}
                  onDelete={id => deleteMut.mutate(id)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Properties section
// ---------------------------------------------------------------------------

function PropertyRow({
  documentId,
  property,
  onDelete,
}: {
  documentId: string
  property: Property
  onDelete: (id: string) => void
}) {
  const [editOpen, setEditOpen] = useState(false)

  return (
    <>
      <TableRow>
        <TableCell className="font-medium">{property.address || '—'}</TableCell>
        <TableCell>{property.city || '—'}</TableCell>
        <TableCell>{property.state || '—'}</TableCell>
        <TableCell>{property.zip || '—'}</TableCell>
        <TableCell className="font-mono text-xs">{property.parcelId || '—'}</TableCell>
        <TableCell className="text-sm max-w-[200px] truncate text-muted-foreground">
          {property.legalDescription || '—'}
        </TableCell>
        <TableCell>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={() => setEditOpen(true)}>Edit</Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => onDelete(property.propertyId)}
            >
              Delete
            </Button>
          </div>
        </TableCell>
      </TableRow>
      {editOpen && (
        <EditPropertyDialog
          documentId={documentId}
          property={property}
          open={editOpen}
          onOpenChange={setEditOpen}
        />
      )}
    </>
  )
}

function PropertiesSection({
  documentId,
  properties,
}: {
  documentId: string
  properties: Property[]
}) {
  const qc = useQueryClient()
  const deleteMut = useMutation({
    mutationFn: (propertyId: string) => deleteProperty(documentId, propertyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents', documentId] }),
  })

  if (properties.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Real Property</CardTitle></CardHeader>
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
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {properties.map(p => (
                <PropertyRow
                  key={p.propertyId}
                  documentId={documentId}
                  property={p}
                  onDelete={id => deleteMut.mutate(id)}
                />
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
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>← Back</Button>
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
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>← Back</Button>
        <div>
          <h1 className="text-2xl font-semibold">Document {doc.docNumber}</h1>
          <p className="text-sm text-muted-foreground">{doc.locationCode} · {doc.recordedDate}</p>
        </div>
      </div>

      {/* Document fields */}
      <Card>
        <CardHeader><CardTitle className="text-base">Filing details</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          <Field label="Doc number"        value={doc.docNumber} />
          <Field label="Recorded date"     value={doc.recordedDate} />
          <Field label="Grantor"           value={doc.grantor} />
          <Field label="Grantee"           value={doc.grantee} />
          <Field label="Document type"     value={doc.docType} />
          <Field label="County"            value={doc.locationCode} />
          <Field label="Book/Vol/Page"     value={doc.bookVolumePage} />
          <Field label="Record number"     value={doc.recordNumber} />
          <Field label="Page number"       value={doc.pageNumber} />
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
      <ContactsSection documentId={documentId!} contacts={data.contacts} />

      {/* Properties */}
      <PropertiesSection documentId={documentId!} properties={data.properties} />
    </div>
  )
}
