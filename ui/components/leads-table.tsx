'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getLeads, getMyLeads } from '@/lib/api'
import type { Lead } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface Props {
  /** If provided, fetches leads for this county path (public). Otherwise uses /auth/leads. */
  locationPath?: string
  /** Show parsed fields column */
  showParsed?: boolean
}

function statusBadge(lead: Lead) {
  if (lead.parsedAt) return <Badge variant="default">Parsed</Badge>
  if (lead.pdfUrl) return <Badge variant="secondary">PDF</Badge>
  return <Badge variant="outline">Raw</Badge>
}

export function LeadsTable({ locationPath, showParsed = false }: Props) {
  const today = new Date().toISOString().slice(0, 10)
  const thirtyDaysAgo = new Date(Date.now() - 30 * 86400_000).toISOString().slice(0, 10)

  const [fromDate, setFromDate] = useState(thirtyDaysAgo)
  const [toDate, setToDate] = useState(today)
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [history, setHistory] = useState<string[]>([])

  const queryKey = locationPath
    ? ['leads', locationPath, fromDate, toDate, cursor]
    : ['my-leads', fromDate, toDate, cursor]

  const { data, isLoading, isError, error } = useQuery({
    queryKey,
    queryFn: () =>
      locationPath
        ? getLeads(locationPath, { from_date: fromDate, to_date: toDate, limit: 50, last_key: cursor })
        : getMyLeads({ from_date: fromDate, to_date: toDate }),
  })

  function goNext() {
    if (data?.nextKey) {
      setHistory((h) => [...h, cursor ?? ''])
      setCursor(data.nextKey)
    }
  }

  function goPrev() {
    const prev = history[history.length - 1]
    setHistory((h) => h.slice(0, -1))
    setCursor(prev || undefined)
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-4 items-end">
        <div className="space-y-1">
          <Label htmlFor="from">From</Label>
          <Input
            id="from"
            type="date"
            value={fromDate}
            onChange={(e) => { setFromDate(e.target.value); setCursor(undefined); setHistory([]) }}
            className="w-36"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="to">To</Label>
          <Input
            id="to"
            type="date"
            value={toDate}
            onChange={(e) => { setToDate(e.target.value); setCursor(undefined); setHistory([]) }}
            className="w-36"
          />
        </div>
        {data && (
          <p className="text-sm text-muted-foreground pb-1">
            {data.count} lead{data.count !== 1 ? 's' : ''}
          </p>
        )}
      </div>

      {/* Table */}
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && (
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : 'Failed to load leads'}
        </p>
      )}
      {data && (
        <div className="rounded-md border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Doc #</TableHead>
                <TableHead>Grantor</TableHead>
                <TableHead>Grantee</TableHead>
                <TableHead>County</TableHead>
                {showParsed && <TableHead>Deceased</TableHead>}
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.leads.length === 0 && (
                <TableRow>
                  <TableCell colSpan={showParsed ? 8 : 7} className="text-center text-muted-foreground py-8">
                    No leads found for this date range.
                  </TableCell>
                </TableRow>
              )}
              {data.leads.map((lead) => (
                <TableRow key={lead.leadId ?? lead.docNumber}>
                  <TableCell className="whitespace-nowrap">{lead.recordedDate}</TableCell>
                  <TableCell className="font-mono text-xs">{lead.docNumber}</TableCell>
                  <TableCell className="max-w-[180px] truncate">{lead.grantor}</TableCell>
                  <TableCell className="max-w-[180px] truncate">{lead.grantee}</TableCell>
                  <TableCell>{lead.locationCode}</TableCell>
                  {showParsed && (
                    <TableCell>{lead.deceasedName ?? '—'}</TableCell>
                  )}
                  <TableCell>{statusBadge(lead)}</TableCell>
                  <TableCell>
                    {lead.pdfUrl && (
                      <a
                        href={lead.pdfUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-primary underline-offset-2 hover:underline"
                      >
                        PDF
                      </a>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {(data?.nextKey || history.length > 0) && (
        <div className="flex gap-2 justify-end">
          <Button variant="outline" size="sm" disabled={history.length === 0} onClick={goPrev}>
            ← Prev
          </Button>
          <Button variant="outline" size="sm" disabled={!data?.nextKey} onClick={goNext}>
            Next →
          </Button>
        </div>
      )}
    </div>
  )
}
