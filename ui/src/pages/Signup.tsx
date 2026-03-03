import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { createCheckoutSession } from '@/lib/api'
import { Button } from '@/components/ui/button'

interface FunnelPayload {
  sub: string
  email: string
  price: number
  type: string
  exp: number
}

function decodeFunnelToken(token: string): FunnelPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    // Base64url decode the payload
    const padded = parts[1].replace(/-/g, '+').replace(/_/g, '/').padEnd(
      parts[1].length + ((4 - (parts[1].length % 4)) % 4),
      '=',
    )
    return JSON.parse(atob(padded)) as FunnelPayload
  } catch {
    return null
  }
}

export default function Signup() {
  const [searchParams]       = useSearchParams()
  const token                = searchParams.get('token') ?? ''
  const [payload, setPayload]= useState<FunnelPayload | null>(null)
  const [loading, setLoading]= useState(false)
  const [error, setError]    = useState<string | null>(null)

  useEffect(() => {
    if (token) setPayload(decodeFunnelToken(token))
  }, [token])

  async function handleSubscribe() {
    if (!token) return
    setError(null)
    setLoading(true)
    try {
      const { url } = await createCheckoutSession(token)
      window.location.href = url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start checkout')
      setLoading(false)
    }
  }

  if (!token || !payload || payload.type !== 'funnel') {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-sm text-center space-y-3">
          <h1 className="text-xl font-semibold">Invalid link</h1>
          <p className="text-sm text-muted-foreground">
            This signup link is missing or has expired. Check your email for a fresh link.
          </p>
        </div>
      </div>
    )
  }

  const expired = payload.exp * 1000 < Date.now()
  if (expired) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-sm text-center space-y-3">
          <h1 className="text-xl font-semibold">Link expired</h1>
          <p className="text-sm text-muted-foreground">
            Your signup link has expired. Contact us for a new one.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-sm w-full space-y-6 text-center">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            Subscribe to Collin County Leads
          </h1>
          <p className="text-sm text-muted-foreground">
            You're subscribing as <span className="font-medium">{payload.email}</span>
          </p>
        </div>

        <div className="rounded-lg border bg-muted/40 p-6 space-y-1">
          <p className="text-4xl font-bold">${payload.price}</p>
          <p className="text-sm text-muted-foreground">per month</p>
          <p className="text-sm text-muted-foreground mt-2">
            Daily probate leads for Collin County, TX
          </p>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <Button
          className="w-full"
          size="lg"
          onClick={handleSubscribe}
          disabled={loading}
        >
          {loading ? 'Redirecting to Stripe…' : `Subscribe for $${payload.price}/mo`}
        </Button>

        <p className="text-xs text-muted-foreground">
          Secure payment powered by Stripe. Cancel anytime.
        </p>
      </div>
    </div>
  )
}
