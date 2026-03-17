import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Mail, CheckCircle2, AlertCircle } from 'lucide-react'

const waitlistSchema = z.object({
  email: z.string().email('Please enter a valid email address').min(1, 'Email is required'),
})

type WaitlistFormData = z.infer<typeof waitlistSchema>

interface WaitlistFormProps {
  onSuccess?: (email: string) => void
  className?: string
  variant?: 'default' | 'minimal'
}

async function joinWaitlist(email: string): Promise<void> {
  const response = await fetch('/real-estate/probate-leads/journeys/accept-waitlist', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email: email.toLowerCase().trim() }),
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Failed to join waitlist' }))
    throw new Error(error.error || 'Failed to join waitlist')
  }
}

export function WaitlistForm({ onSuccess, className = '', variant = 'default' }: WaitlistFormProps) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors },
    getValues,
  } = useForm<WaitlistFormData>()

  const onSubmit = async (data: WaitlistFormData) => {
    setStatus('loading')
    setErrorMessage(null)

    try {
      await joinWaitlist(data.email)
      setStatus('success')
      onSuccess?.(data.email)
    } catch (error) {
      setStatus('error')
      setErrorMessage(error instanceof Error ? error.message : 'Failed to join waitlist')
    }
  }

  if (status === 'success') {
    const email = getValues('email')

    if (variant === 'minimal') {
      return (
        <div className={`text-center space-y-3 ${className}`}>
          <div className="flex items-center justify-center gap-2 text-green-600 dark:text-green-400">
            <CheckCircle2 className="h-5 w-5" />
            <span className="font-medium">You're on the waitlist!</span>
          </div>
          <p className="text-sm text-muted-foreground">
            We'll email <span className="font-medium">{email}</span> when we launch.
          </p>
        </div>
      )
    }

    return (
      <Card className={className}>
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <div className="rounded-full bg-green-100 dark:bg-green-900 p-3">
              <CheckCircle2 className="h-6 w-6 text-green-600 dark:text-green-400" />
            </div>
          </div>
          <CardTitle>You're on the waitlist!</CardTitle>
          <CardDescription>
            We'll email <span className="font-medium">{email}</span> when we launch.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="rounded-lg bg-muted p-4">
              <h4 className="font-medium text-sm mb-2">What happens next?</h4>
              <ul className="text-sm text-muted-foreground space-y-1">
                <li>• Exclusive previews as we prepare to launch</li>
                <li>• Personal invitation before anyone else</li>
                <li>• Early access to fresh probate opportunities</li>
              </ul>
            </div>
            <p className="text-xs text-muted-foreground text-center">
              Expected launch: ~15 days from now
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (variant === 'minimal') {
    return (
      <form onSubmit={handleSubmit(onSubmit)} className={`space-y-3 ${className}`}>
        <div className="space-y-2">
          <div className="flex gap-2">
            <div className="flex-1">
              <Input
                {...register('email')}
                type="email"
                placeholder="Enter your email"
                className="h-10"
                disabled={status === 'loading'}
              />
            </div>
            <Button
              type="submit"
              disabled={status === 'loading'}
              className="h-10 px-6"
            >
              {status === 'loading' ? (
                <div className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
              ) : (
                'Join Waitlist'
              )}
            </Button>
          </div>
          {errors.email && (
            <p className="text-xs text-destructive">{errors.email.message}</p>
          )}
          {status === 'error' && errorMessage && (
            <p className="text-xs text-destructive flex items-center gap-1">
              <AlertCircle className="h-3 w-3" />
              {errorMessage}
            </p>
          )}
        </div>
      </form>
    )
  }

  return (
    <Card className={className}>
      <CardHeader className="text-center">
        <div className="flex justify-center mb-2">
          <div className="rounded-full bg-blue-100 dark:bg-blue-900 p-3">
            <Mail className="h-6 w-6 text-blue-600 dark:text-blue-400" />
          </div>
        </div>
        <CardTitle>Join Our Waitlist</CardTitle>
        <CardDescription>
          Be the first to know when Collin County Probate Leads launches
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email address</Label>
            <Input
              {...register('email')}
              id="email"
              type="email"
              placeholder="you@example.com"
              disabled={status === 'loading'}
            />
            {errors.email && (
              <p className="text-sm text-destructive">{errors.email.message}</p>
            )}
          </div>

          {status === 'error' && errorMessage && (
            <div className="rounded-md bg-destructive/10 border border-destructive/20 p-3">
              <div className="flex items-center gap-2 text-destructive">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                <p className="text-sm">{errorMessage}</p>
              </div>
            </div>
          )}

          <Button
            type="submit"
            className="w-full"
            disabled={status === 'loading'}
          >
            {status === 'loading' ? (
              <>
                <div className="animate-spin mr-2 h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
                Joining waitlist...
              </>
            ) : (
              'Join Waitlist'
            )}
          </Button>

          <p className="text-xs text-muted-foreground text-center">
            We'll notify you the moment we launch. No spam, unsubscribe anytime.
          </p>
        </form>
      </CardContent>
    </Card>
  )
}
