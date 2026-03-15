import { useQuery } from '@tanstack/react-query'
import { Navigate, useSearchParams } from 'react-router-dom'
import { getMe } from '@/lib/api'
import { LeadsTable } from '@/components/leads-table'
import { Badge } from '@/components/ui/badge'

const statusVariant: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  active:   'default',
  trialing: 'secondary',
  past_due: 'destructive',
  canceled: 'outline',
  inactive: 'outline',
}

export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const checkoutSuccess = searchParams.get('checkout') === 'success'

  const { data: user, isLoading, isError } = useQuery({
    queryKey: ['me'],
    queryFn:  getMe,
    // Poll every 3 s while checkout=success and subscription not yet active
    refetchInterval: (query) => {
      const u = query.state.data
      return checkoutSuccess && u?.status !== 'active' ? 3000 : false
    },
  })

  // Once status reaches active, clear the ?checkout=success param
  if (checkoutSuccess && user?.status === 'active') {
    setSearchParams({})
  }

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (isError || !user) return <Navigate to="/login" replace />

  const variant  = statusVariant[user.status] ?? 'outline'
  const isActive = user.status === 'active' || user.status === 'trialing'

  return (
    <div className="space-y-6">
      {/* Checkout-pending activation banner */}
      {checkoutSuccess && user.status !== 'active' && (
        <div className="rounded-md border border-primary/30 bg-primary/5 px-4 py-3 text-sm text-primary flex items-center gap-2">
          <span className="animate-spin inline-block h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
          Activating your subscription…
        </div>
      )}

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Your leads</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {user.locationCodes.length > 0
              ? `Showing leads for: ${user.locationCodes.join(', ')}`
              : 'No counties selected — update your account to add counties.'}
          </p>
        </div>
        <Badge variant={variant}>{user.status}</Badge>
      </div>

      {!isActive ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          Your subscription is <strong>{user.status}</strong>. Renew to access leads.
        </div>
      ) : (
        <LeadsTable showParsed />
      )}
    </div>
  )
}
