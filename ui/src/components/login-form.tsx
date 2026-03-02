import { useState } from 'react'
import { requestLogin } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type State = 'idle' | 'loading' | 'sent' | 'error'

export function LoginForm() {
  const [email, setEmail] = useState('')
  const [state, setState] = useState<State>('idle')
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setState('loading')
    try {
      await requestLogin(email)
      setState('sent')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
      setState('error')
    }
  }

  if (state === 'sent') {
    return (
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Check your email</CardTitle>
          <CardDescription>
            We sent a magic link to <strong>{email}</strong>. Click it to sign in.
            The link expires in 15 minutes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="ghost" className="w-full" onClick={() => setState('idle')}>
            Use a different email
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>Enter your email and we'll send you a magic link.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>
          {state === 'error' && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={state === 'loading'}>
            {state === 'loading' ? 'Sending…' : 'Send magic link'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
