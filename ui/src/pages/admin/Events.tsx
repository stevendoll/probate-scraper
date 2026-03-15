import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminListAllEvents, type AdminEventsParams } from '@/lib/api'
import type { AppEvent } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

const EVENT_TYPES = [
  'email_sent',
  'email_open',
  'link_clicked',
  'subscribe_clicked',
  'signup_completed',
  'feedback',
]

const typeBadgeVariant: Record<string, 'default' | 'secondary' | 'outline'> = {
  email_sent:       'outline',
  email_open:       'secondary',
  link_clicked:     'secondary',
  subscribe_clicked:'default',
  signup_completed: 'default',
  feedback:         'outline',
}

function MetadataPreview({ metadata }: { metadata?: Record<string, unknown> }) {
  if (!metadata) return <span className="text-muted-foreground">—</span>
  const entries = Object.entries(metadata).filter(([, v]) => v !== '' && v !== null && v !== undefined)
  if (!entries.length) return <span className="text-muted-foreground">—</span>
  return (
    <span className="text-xs text-muted-foreground truncate max-w-[200px] block">
      {entries.map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}
    </span>
  )
}

export default function AdminEvents() {
  const [filters, setFilters] = useState<AdminEventsParams>({})
  const [draft, setDraft]     = useState<AdminEventsParams>({})

  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-events', filters],
    queryFn:  () => adminListAllEvents({ ...filters, limit: 100 }),
  })

  function applyFilters() {
    setFilters({ ...draft })
  }

  function clearFilters() {
    setDraft({})
    setFilters({})
  }

  const events: AppEvent[] = data?.events ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Events</h1>
        <span className="text-sm text-muted-foreground">{data?.count ?? 0} results</span>
      </div>

      {/* Filter bar */}
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <div className="grid sm:grid-cols-4 gap-3">
          <div>
            <label className="block text-xs font-medium mb-1">User ID</label>
            <input
              type="text"
              value={draft.user_id ?? ''}
              onChange={e => setDraft(d => ({ ...d, user_id: e.target.value || undefined }))}
              placeholder="filter by user…"
              className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div>
            <label className="block text-xs font-medium mb-1">Event type</label>
            <select
              value={draft.event_type ?? ''}
              onChange={e => setDraft(d => ({ ...d, event_type: e.target.value || undefined }))}
              className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">All types</option>
              {EVENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1">From date</label>
            <input
              type="date"
              value={draft.from_date ?? ''}
              onChange={e => setDraft(d => ({ ...d, from_date: e.target.value || undefined }))}
              className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div>
            <label className="block text-xs font-medium mb-1">To date</label>
            <input
              type="date"
              value={draft.to_date ?? ''}
              onChange={e => setDraft(d => ({ ...d, to_date: e.target.value || undefined }))}
              className="w-full rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={applyFilters}>Apply</Button>
          <Button size="sm" variant="outline" onClick={clearFilters}>Clear</Button>
        </div>
      </div>

      {/* Table */}
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError   && <p className="text-sm text-destructive">Failed to load events.</p>}
      {!isLoading && !isError && (
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/40">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Timestamp</th>
                <th className="px-4 py-2 text-left font-medium">User ID</th>
                <th className="px-4 py-2 text-left font-medium">Type</th>
                <th className="px-4 py-2 text-left font-medium">Variant</th>
                <th className="px-4 py-2 text-left font-medium">Metadata</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {events.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                    No events found.
                  </td>
                </tr>
              ) : events.map(ev => (
                <tr key={ev.event_id} className="hover:bg-muted/20 transition-colors">
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground whitespace-nowrap">
                    {ev.timestamp.slice(0, 19).replace('T', ' ')}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">
                    <span title={ev.user_id}>{ev.user_id.slice(0, 8)}…</span>
                  </td>
                  <td className="px-4 py-2">
                    <Badge variant={typeBadgeVariant[ev.event_type] ?? 'outline'} className="text-xs">
                      {ev.event_type}
                    </Badge>
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
                    {ev.variant || '—'}
                  </td>
                  <td className="px-4 py-2">
                    <MetadataPreview metadata={ev.metadata} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
