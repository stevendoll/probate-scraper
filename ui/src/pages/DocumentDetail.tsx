import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getDocument, parseDocument,
  updateContact, deleteContact,
  updateProperty, deleteProperty,
  createLink, deleteLink,
} from '@/lib/api'
import type { Contact, Link, Property } from '@/lib/types'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { CheckCircle, ExternalLink, Plus, X } from 'lucide-react'

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
// Link helpers
// ---------------------------------------------------------------------------

const LINK_TYPE_LABELS: Record<string, string> = {
  zillow:        'Zillow',
  realtor:       'Realtor.com',
  redfin:        'Redfin',
  google_maps:   'Google Maps',
  county_record: 'County Record',
  obituary:      'Obituary',
  legacy:        'Legacy.com',
  findagrave:    'FindAGrave',
  other:         'Link',
}

type Suggestion = { label: string; url: string; linkType: string }

function propertyLinkSuggestions(property: Property): Suggestion[] {
  const addr = [property.address, property.city, property.state, property.zip]
    .filter(Boolean)
    .join(', ')
  const q = encodeURIComponent(addr)
  return [
    { label: 'Zillow',        url: `https://www.zillow.com/homes/${q}_rb/`,                  linkType: 'zillow' },
    { label: 'Redfin',        url: `https://www.redfin.com/search/real-estate?q=${q}`,        linkType: 'redfin' },
    { label: 'Realtor.com',   url: `https://www.realtor.com/realestateandhomes-search/${q}`,  linkType: 'realtor' },
    { label: 'Google Maps',   url: `https://www.google.com/maps/search/?api=1&query=${q}`,    linkType: 'google_maps' },
    { label: 'County Record', url: 'https://www.collincad.org/propertysearch',                linkType: 'county_record' },
  ]
}

function contactLinkSuggestions(contact: Contact): Suggestion[] {
  const name   = contact.name || ''
  const parts  = name.trim().split(/\s+/)
  const first  = encodeURIComponent(parts[0] || '')
  const last   = encodeURIComponent(parts.length > 1 ? parts[parts.length - 1] : '')
  const full   = encodeURIComponent(name)
  return [
    { label: 'Legacy.com',      url: `https://www.legacy.com/search?name=${full}`,                                                      linkType: 'legacy' },
    { label: 'FindAGrave',      url: `https://www.findagrave.com/memorial/search?firstname=${first}&lastname=${last}`,                  linkType: 'findagrave' },
    { label: 'Obituaries.com',  url: `https://www.obituaries.com/search/results/?fname=${first}&lname=${last}`,                        linkType: 'obituary' },
    { label: 'Google obituary', url: `https://www.google.com/search?q=${full}+obituary`,                                               linkType: 'obituary' },
  ]
}

// ---------------------------------------------------------------------------
// LinkChip
// ---------------------------------------------------------------------------

const LINK_FAVICONS: Record<string, string> = {
  zillow:        'https://www.google.com/s2/favicons?domain=zillow.com&sz=16',
  realtor:       'https://www.google.com/s2/favicons?domain=realtor.com&sz=16',
  redfin:        'https://www.google.com/s2/favicons?domain=redfin.com&sz=16',
  google_maps:   'https://www.google.com/s2/favicons?domain=maps.google.com&sz=16',
  county_record: 'https://www.google.com/s2/favicons?domain=car.org&sz=16',
  obituary:      'https://www.google.com/s2/favicons?domain=obituaries.com&sz=16',
  legacy:        'https://www.google.com/s2/favicons?domain=legacy.com&sz=16',
  findagrave:    'https://www.google.com/s2/favicons?domain=findagrave.com&sz=16',
}

function LinkChip({ link, onDelete }: { link: Link; onDelete: () => void }) {
  const favicon = LINK_FAVICONS[link.linkType]
  return (
    <span className="group inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
      <a
        href={link.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-1 hover:text-foreground"
      >
        {favicon
          ? <img src={favicon} alt="" className="h-3 w-3 shrink-0" />
          : <ExternalLink size={10} />
        }
        {link.label || LINK_TYPE_LABELS[link.linkType] || 'Link'}
      </a>
      <button
        type="button"
        onClick={onDelete}
        className="ml-0.5 opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
        aria-label="Remove link"
      >
        <X size={10} />
      </button>
    </span>
  )
}

// ---------------------------------------------------------------------------
// AddLinkDialog
// ---------------------------------------------------------------------------

interface LinkFormState {
  label:    string
  url:      string
  linkType: string
  notes:    string
}

function AddLinkDialog({
  documentId,
  parentId,
  parentType,
  contextName,
  suggestions,
  open,
  onOpenChange,
}: {
  documentId:   string
  parentId:     string
  parentType:   'contact' | 'property'
  contextName:  string
  suggestions:  Suggestion[]
  open:         boolean
  onOpenChange: (o: boolean) => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState<LinkFormState>({ label: '', url: '', linkType: 'other', notes: '' })

  const mut = useMutation({
    mutationFn: () =>
      createLink(documentId, parentId, parentType, {
        label:     form.label,
        url:       form.url,
        link_type: form.linkType,
        notes:     form.notes,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents', documentId] })
      setForm({ label: '', url: '', linkType: 'other', notes: '' })
      onOpenChange(false)
    },
  })

  const applySuggestion = (s: Suggestion) => {
    setForm(prev => ({ ...prev, label: s.label, url: s.url, linkType: s.linkType }))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add link — {contextName}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">Quick suggestions</p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map(s => (
                <Button
                  key={s.label}
                  variant="outline"
                  size="sm"
                  type="button"
                  onClick={() => applySuggestion(s)}
                  className="h-7 text-xs"
                >
                  {s.label}
                </Button>
              ))}
            </div>
          </div>
          <div className="grid gap-3">
            <div className="grid grid-cols-4 items-center gap-4">
              <Label className="text-right">Label</Label>
              <Input
                className="col-span-3"
                placeholder="e.g. Zillow listing"
                value={form.label}
                onChange={e => setForm(prev => ({ ...prev, label: e.target.value }))}
              />
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label className="text-right">URL</Label>
              <Input
                className="col-span-3"
                placeholder="https://…"
                value={form.url}
                onChange={e => setForm(prev => ({ ...prev, url: e.target.value }))}
              />
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label className="text-right">Type</Label>
              <Select
                value={form.linkType}
                onValueChange={v => setForm(prev => ({ ...prev, linkType: v }))}
              >
                <SelectTrigger className="col-span-3">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="zillow">Zillow</SelectItem>
                  <SelectItem value="realtor">Realtor.com</SelectItem>
                  <SelectItem value="redfin">Redfin</SelectItem>
                  <SelectItem value="google_maps">Google Maps</SelectItem>
                  <SelectItem value="county_record">County Record</SelectItem>
                  <SelectItem value="obituary">Obituary</SelectItem>
                  <SelectItem value="legacy">Legacy.com</SelectItem>
                  <SelectItem value="findagrave">FindAGrave</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-4 items-center gap-4">
              <Label className="text-right">Notes</Label>
              <Input
                className="col-span-3"
                value={form.notes}
                onChange={e => setForm(prev => ({ ...prev, notes: e.target.value }))}
              />
            </div>
          </div>
        </div>
        {mut.isError && (
          <p className="px-1 text-sm text-destructive">
            {mut.error instanceof Error ? mut.error.message : 'Save failed'}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => mut.mutate()} disabled={mut.isPending || !form.url}>
            {mut.isPending ? 'Saving…' : 'Add link'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
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
  const qc = useQueryClient()
  const [editOpen, setEditOpen] = useState(false)
  const [addLinkOpen, setAddLinkOpen] = useState(false)

  const deleteLinkMut = useMutation({
    mutationFn: (linkId: string) => deleteLink(documentId, contact.contactId, 'contact', linkId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents', documentId] }),
  })

  const links = contact.links ?? []

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

      {/* Links sub-row */}
      <TableRow className="hover:bg-transparent border-t-0">
        <TableCell colSpan={8} className="pb-2 pt-0 pl-6">
          <div className="flex flex-wrap items-center gap-1.5">
            {links.map(link => (
              <LinkChip
                key={link.linkId}
                link={link}
                onDelete={() => deleteLinkMut.mutate(link.linkId)}
              />
            ))}
            <Button
              variant="ghost"
              size="sm"
              className="h-6 gap-1 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setAddLinkOpen(true)}
            >
              <Plus size={11} /> Add link
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
      {addLinkOpen && (
        <AddLinkDialog
          documentId={documentId}
          parentId={contact.contactId}
          parentType="contact"
          contextName={contact.name || 'contact'}
          suggestions={contactLinkSuggestions(contact)}
          open={addLinkOpen}
          onOpenChange={setAddLinkOpen}
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
  const qc = useQueryClient()
  const [editOpen, setEditOpen] = useState(false)
  const [addLinkOpen, setAddLinkOpen] = useState(false)

  const deleteLinkMut = useMutation({
    mutationFn: (linkId: string) => deleteLink(documentId, property.propertyId, 'property', linkId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents', documentId] }),
  })

  const links = property.links ?? []

  return (
    <>
      <TableRow>
        <TableCell className="font-medium">
          <span className="flex items-center gap-1.5">
            {property.address || '—'}
            {property.isVerified && (
              <CheckCircle
                className="shrink-0 text-green-500"
                size={14}
                aria-label="Address verified"
              />
            )}
          </span>
        </TableCell>
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

      {/* Links sub-row */}
      <TableRow className="hover:bg-transparent border-t-0">
        <TableCell colSpan={7} className="pb-2 pt-0 pl-6">
          <div className="flex flex-wrap items-center gap-1.5">
            {links.map(link => (
              <LinkChip
                key={link.linkId}
                link={link}
                onDelete={() => deleteLinkMut.mutate(link.linkId)}
              />
            ))}
            <Button
              variant="ghost"
              size="sm"
              className="h-6 gap-1 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setAddLinkOpen(true)}
            >
              <Plus size={11} /> Add link
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
      {addLinkOpen && (
        <AddLinkDialog
          documentId={documentId}
          parentId={property.propertyId}
          parentType="property"
          contextName={property.address || 'property'}
          suggestions={propertyLinkSuggestions(property)}
          open={addLinkOpen}
          onOpenChange={setAddLinkOpen}
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
  const qc = useQueryClient()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['documents', documentId],
    queryFn: () => getDocument(documentId!),
    enabled: !!documentId,
  })

  const parseMut = useMutation({
    mutationFn: () => parseDocument(documentId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents', documentId] }),
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
        <div className="flex-1">
          <h1 className="text-2xl font-semibold">Document {doc.docNumber}</h1>
          <p className="text-sm text-muted-foreground">{doc.locationCode} · {doc.recordedDate}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => parseMut.mutate()}
          disabled={parseMut.isPending}
        >
          {parseMut.isPending ? 'Parsing…' : 'Parse document'}
        </Button>
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
          <Field label="Parsed at"     value={doc.parsedAt} />
        </CardContent>
      </Card>

      {/* Parse result */}
      {(doc.parsedAt || doc.parseError) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Parse result</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {doc.parseError ? (
              <p className="text-sm text-destructive font-mono">{doc.parseError}</p>
            ) : (
              <>
                {doc.summary && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Summary</p>
                    <p className="text-sm">{doc.summary}</p>
                  </div>
                )}
                {doc.rawResponse && (
                  <details className="group">
                    <summary className="cursor-pointer text-xs font-medium text-muted-foreground uppercase tracking-wide select-none hover:text-foreground">
                      Raw Bedrock response
                    </summary>
                    <pre className="mt-2 text-xs bg-muted rounded p-3 overflow-auto max-h-96 whitespace-pre-wrap break-words">
                      {(() => {
                        try { return JSON.stringify(JSON.parse(doc.rawResponse!), null, 2) }
                        catch { return doc.rawResponse }
                      })()}
                    </pre>
                  </details>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* Contacts */}
      <ContactsSection documentId={documentId!} contacts={data.contacts} />

      {/* Properties */}
      <PropertiesSection documentId={documentId!} properties={data.properties} />
    </div>
  )
}
