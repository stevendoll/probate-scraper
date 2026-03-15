import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { submitFeedback } from '@/lib/api'

interface FeedbackWidgetProps {
  title?: string
  source: string
  defaultEmail?: string
}

type State = 'idle' | 'submitting' | 'success' | 'error'

export function FeedbackWidget({
  title = 'Send feedback',
  source,
  defaultEmail = '',
}: FeedbackWidgetProps) {
  const [message, setMessage] = useState('')
  const [email, setEmail]     = useState(defaultEmail)
  const [state, setState]     = useState<State>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!message.trim()) return
    setState('submitting')
    setErrorMsg('')
    try {
      await submitFeedback({ message: message.trim(), source, email: email.trim() || undefined })
      setState('success')
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Something went wrong')
      setState('error')
    }
  }

  if (state === 'success') {
    return (
      <div className="rounded-lg border bg-card p-6 text-center space-y-2">
        <p className="font-medium">Thanks, we'll be in touch.</p>
        <p className="text-sm text-muted-foreground">Your feedback has been sent.</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border bg-card p-6 space-y-4">
      <h3 className="font-semibold text-base">{title}</h3>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor={`feedback-msg-${source}`}>
            Your message
          </label>
          <textarea
            id={`feedback-msg-${source}`}
            value={message}
            onChange={e => setMessage(e.target.value)}
            rows={4}
            required
            placeholder="Tell us what you think…"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor={`feedback-email-${source}`}>
            Your email <span className="text-muted-foreground font-normal">(optional)</span>
          </label>
          <input
            id={`feedback-email-${source}`}
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        {state === 'error' && (
          <p className="text-sm text-destructive">{errorMsg}</p>
        )}

        <Button type="submit" disabled={state === 'submitting' || !message.trim()}>
          {state === 'submitting' ? 'Sending…' : 'Send feedback'}
        </Button>
      </form>
    </div>
  )
}
