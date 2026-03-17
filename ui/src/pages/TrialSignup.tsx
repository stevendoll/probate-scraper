import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, Clock, Zap, Gift } from 'lucide-react'

interface ProspectPayload {
  sub: string
  email: string
  price: number
  type: string
  exp: number
}

function decodeProspectToken(token: string): ProspectPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const padded = parts[1].replace(/-/g, '+').replace(/_/g, '/').padEnd(
      parts[1].length + ((4 - (parts[1].length % 4)) % 4),
      '=',
    )
    return JSON.parse(atob(padded)) as ProspectPayload
  } catch {
    return null
  }
}

async function startTrial(token: string): Promise<void> {
  const response = await fetch('/real-estate/probate-leads/journeys/start-trial', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ token }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Failed to start trial' }))
    throw new Error(error.error || 'Failed to start trial')
  }

  return response.json()
}

export default function TrialSignup() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token') ?? ''

  const [payload, setPayload] = useState<ProspectPayload | null>(null)
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (token) setPayload(decodeProspectToken(token))
  }, [token])

  const handleStartTrial = async () => {
    if (!token) return
    setError(null)
    setStatus('loading')

    try {
      await startTrial(token)
      setStatus('success')
      // Redirect to login after successful trial start
      setTimeout(() => navigate('/login'), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start trial')
      setStatus('error')
    }
  }

  if (!token || !payload || payload.type !== 'prospect') {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <Card className="max-w-sm">
          <CardHeader>
            <CardTitle>Invalid Trial Link</CardTitle>
            <CardDescription>
              This trial invitation link is missing or invalid. Check your email for a fresh link.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  const expired = payload.exp * 1000 < Date.now()
  if (expired) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <Card className="max-w-sm">
          <CardHeader>
            <CardTitle>Trial Invitation Expired</CardTitle>
            <CardDescription>
              Your free trial invitation has expired. Contact us for a new invitation.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  if (status === 'success') {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <Card className="max-w-md">
          <CardHeader className="text-center">
            <div className="flex justify-center mb-2">
              <div className="rounded-full bg-green-100 dark:bg-green-900 p-3">
                <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
              </div>
            </div>
            <CardTitle>🎉 Your Free Trial is Active!</CardTitle>
            <CardDescription>
              You now have 14 days of unlimited access to Collin County probate leads.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="rounded-lg bg-muted p-4">
                <h4 className="font-medium text-sm mb-2">What's included in your trial:</h4>
                <ul className="text-sm text-muted-foreground space-y-1">
                  <li>• Fresh daily probate filings</li>
                  <li>• Complete property details</li>
                  <li>• Contact information for all parties</li>
                  <li>• Advanced search and filtering</li>
                </ul>
              </div>
              <p className="text-sm text-center text-muted-foreground">
                Redirecting you to sign in...
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-lg w-full space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="flex justify-center mb-4">
            <div className="rounded-full bg-blue-100 dark:bg-blue-900 p-4">
              <Gift className="h-8 w-8 text-blue-600 dark:text-blue-400" />
            </div>
          </div>
          <h1 className="text-3xl font-bold tracking-tight">
            Start Your Free Trial
          </h1>
          <p className="text-muted-foreground">
            You've been invited to try Collin County Probate Leads free for 14 days
          </p>
          <div className="flex justify-center">
            <Badge variant="secondary" className="text-xs">
              <Clock className="h-3 w-3 mr-1" />
              No credit card required
            </Badge>
          </div>
        </div>

        {/* Trial Details */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-5 w-5 text-amber-500" />
              14-Day Free Trial
            </CardTitle>
            <CardDescription>
              Full access to all features. Try risk-free.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="grid gap-3">
                <div className="flex items-start gap-3">
                  <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="font-medium">Fresh Daily Probate Filings</p>
                    <p className="text-sm text-muted-foreground">
                      Updated every day from Collin County records
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="font-medium">Complete Property Details</p>
                    <p className="text-sm text-muted-foreground">
                      Addresses, values, and legal descriptions
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="font-medium">Contact Information</p>
                    <p className="text-sm text-muted-foreground">
                      Executors, heirs, and attorney details
                    </p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="font-medium">Advanced Search Tools</p>
                    <p className="text-sm text-muted-foreground">
                      Filter by property value, date, and more
                    </p>
                  </div>
                </div>
              </div>

              <div className="border-t pt-4">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-muted-foreground">After trial ends:</span>
                  <span className="font-medium">${payload.price}/month</span>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Cancel anytime during trial with no charges
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* User Info */}
        <div className="rounded-lg border bg-muted/40 p-4">
          <p className="text-sm text-muted-foreground">
            Starting trial for: <span className="font-medium text-foreground">{payload.email}</span>
          </p>
        </div>

        {/* Error Display */}
        {status === 'error' && error && (
          <div className="rounded-md bg-destructive/10 border border-destructive/20 p-4">
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}

        {/* Action Button */}
        <Button
          size="lg"
          className="w-full"
          onClick={handleStartTrial}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? (
            <>
              <div className="animate-spin mr-2 h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
              Starting your free trial...
            </>
          ) : (
            'Start My Free Trial'
          )}
        </Button>

        <p className="text-xs text-muted-foreground text-center">
          By starting your trial, you agree to our terms of service.
          Your trial will automatically expire after 14 days.
        </p>
      </div>
    </div>
  )
}
