import { useState } from 'react'
import { requestLogin } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type State = 'idle' | 'loading' | 'sent' | 'error'

export function LoginForm() {
  const [email, setEmail] = useState('')
  const [state, setState] = useState<State>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setState('loading')
    setErrorMsg('')
    try {
      await requestLogin(email)
      setState('sent')
    } catch (err) {
      setState('error')
      setErrorMsg(err instanceof Error ? err.message : 'Something went wrong')
    }
  }

  if (state === 'sent') {
    return (
      <div className="space-y-2 text-center">
        <p className="text-lg font-medium">Check your email</p>
        <p className="text-sm text-muted-foreground">
          We sent a sign-in link to <strong>{email}</strong>.
          <br />
          The link expires in 15 minutes.
        </p>
        <Button variant="ghost" size="sm" onClick={() => setState('idle')}>
          Use a different email
        </Button>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="email">Email address</Label>
        <Input
          id="email"
          type="email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
          autoFocus
        />
      </div>
      {state === 'error' && <p className="text-sm text-destructive">{errorMsg}</p>}
      <Button type="submit" className="w-full" disabled={state === 'loading'}>
        {state === 'loading' ? 'Sending…' : 'Send magic link'}
      </Button>
    </form>
  )
}
