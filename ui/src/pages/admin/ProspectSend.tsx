import { useState } from 'react'
import { adminSendProspect } from '@/lib/api'
import type { ProspectSendResult } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export default function ProspectSend() {
  const [emailsText, setEmailsText]   = useState('')
  const [leadCount, setLeadCount]     = useState(10)
  const [journeyType, setJourneyType] = useState('prospect')
  const [results, setResults]         = useState<ProspectSendResult[] | null>(null)
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setResults(null)

    const emails = emailsText
      .split(/[\n,]+/)
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean)

    if (emails.length === 0) {
      setError('Enter at least one email address.')
      return
    }

    setLoading(true)
    try {
      const resp = await adminSendProspect(emails, leadCount, journeyType)
      setResults(resp.results)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold">Send Prospect Emails</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Create users in the selected customer journey and send them personalized emails.
          Journey types determine email content and user flow.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1">
          <label className="text-sm font-medium" htmlFor="emails">
            Email addresses (one per line or comma-separated)
          </label>
          <textarea
            id="emails"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono min-h-32 resize-y focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="prospect1@example.com&#10;prospect2@example.com"
            value={emailsText}
            onChange={(e) => setEmailsText(e.target.value)}
            disabled={loading}
          />
        </div>

        <div className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm font-medium">Customer Journey Type</label>
            <Select value={journeyType} onValueChange={setJourneyType} disabled={loading}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="prospect">
                  Prospect - Traditional leads email with subscribe link & pricing
                </SelectItem>
                <SelectItem value="coming_soon">
                  Coming Soon - Waitlist invitation for early access
                </SelectItem>
                <SelectItem value="free_trial">
                  Free Trial - Direct trial invitation (14-day trial)
                </SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {journeyType === 'prospect' && 'Users will be created as prospects and receive leads samples with pricing.'}
              {journeyType === 'coming_soon' && 'Users will be invited to join the waitlist for early access.'}
              {journeyType === 'free_trial' && 'Users will get immediate trial access with 14-day expiration.'}
            </p>
          </div>

          {journeyType === 'prospect' && (
            <div className="space-y-1">
              <label className="text-sm font-medium" htmlFor="leadCount">
                Sample leads to include (1–50)
              </label>
              <input
                id="leadCount"
                type="number"
                min={1}
                max={50}
                className="w-28 rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={leadCount}
                onChange={(e) => setLeadCount(Number(e.target.value))}
                disabled={loading}
              />
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <Button type="submit" disabled={loading}>
          {loading ? 'Sending…' : 'Send Prospect Emails'}
        </Button>
      </form>

      {results && (
        <div className="space-y-2">
          <h2 className="text-lg font-medium">Results</h2>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Price</TableHead>
                  <TableHead>Message</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((r) => (
                  <TableRow key={r.email}>
                    <TableCell className="font-mono text-sm">{r.email}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          r.status === 'sent'
                            ? 'default'
                            : r.status === 'error'
                              ? 'destructive'
                              : 'outline'
                        }
                      >
                        {r.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {r.price != null ? `$${r.price}/mo` : '—'}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {r.message ?? '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="text-xs text-muted-foreground">
            {results.filter((r) => r.status === 'sent').length} of {results.length} sent.
          </p>
        </div>
      )}
    </div>
  )
}
