import { requireAuth, fetchMe } from '@/lib/auth'
import { LeadsTable } from '@/components/leads-table'
import { Badge } from '@/components/ui/badge'

export const metadata = { title: 'Dashboard — Probate Leads' }

export default async function DashboardPage() {
  const { token } = await requireAuth()
  const user = await fetchMe(token)

  const statusColor: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
    active: 'default',
    trialing: 'secondary',
    past_due: 'destructive',
    canceled: 'outline',
    inactive: 'outline',
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Your leads</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {user.locationCodes.length > 0
              ? `Showing leads for: ${user.locationCodes.join(', ')}`
              : 'No counties selected — update your account to add counties.'}
          </p>
        </div>
        <Badge variant={statusColor[user.status] ?? 'outline'}>{user.status}</Badge>
      </div>

      {user.status !== 'active' && user.status !== 'trialing' ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Your subscription is <strong>{user.status}</strong>. Renew to access leads.
        </div>
      ) : (
        <LeadsTable showParsed />
      )}
    </div>
  )
}
