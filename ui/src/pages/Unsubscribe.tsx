import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { unsubscribe } from '@/lib/api'
import { Button } from '@/components/ui/button'

export default function Unsubscribe() {
  const [searchParams]        = useSearchParams()
  const token                 = searchParams.get('token') ?? ''
  const [loading, setLoading] = useState(false)
  const [done, setDone]       = useState(false)
  const [error, setError]     = useState<string | null>(null)

  async function handleUnsubscribe() {
    if (!token) return
    setError(null)
    setLoading(true)
    try {
      await unsubscribe(token)
      setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to unsubscribe')
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-sm text-center space-y-3">
          <h1 className="text-xl font-semibold">Invalid link</h1>
          <p className="text-sm text-muted-foreground">
            This unsubscribe link is missing or invalid.
          </p>
        </div>
      </div>
    )
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-sm text-center space-y-3">
          <h1 className="text-xl font-semibold">You've been unsubscribed</h1>
          <p className="text-sm text-muted-foreground">
            You won't receive any more emails from us. If this was a mistake,
            contact us to reactivate.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-sm w-full text-center space-y-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">Unsubscribe</h1>
          <p className="text-sm text-muted-foreground">
            Are you sure you want to stop receiving Collin County Probate Leads emails?
          </p>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex flex-col gap-3">
          <Button
            variant="destructive"
            className="w-full"
            onClick={handleUnsubscribe}
            disabled={loading}
          >
            {loading ? 'Unsubscribing…' : 'Yes, unsubscribe me'}
          </Button>
          <Button
            variant="outline"
            className="w-full"
            onClick={() => window.history.back()}
            disabled={loading}
          >
            Cancel
          </Button>
        </div>
      </div>
    </div>
  )
}
