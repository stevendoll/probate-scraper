'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { verifyMagicToken } from '@/lib/api'

type State = 'verifying' | 'success' | 'error'

export default function VerifyPage() {
  const router = useRouter()
  const params = useSearchParams()
  const [state, setState] = useState<State>('verifying')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    const token = params.get('token')
    if (!token) {
      setState('error')
      setErrorMsg('No token found in the link.')
      return
    }

    verifyMagicToken(token)
      .then((data) => {
        setState('success')
        // Redirect based on role
        const dest = data.user.role === 'admin' ? '/admin/users' : '/dashboard'
        router.replace(dest)
      })
      .catch((err) => {
        setState('error')
        setErrorMsg(err instanceof Error ? err.message : 'Invalid or expired link.')
      })
  }, [params, router])

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="text-center space-y-3 max-w-sm">
        {state === 'verifying' && (
          <>
            <p className="text-lg font-medium">Signing you in…</p>
            <p className="text-sm text-muted-foreground">Please wait a moment.</p>
          </>
        )}
        {state === 'success' && (
          <>
            <p className="text-lg font-medium">Success!</p>
            <p className="text-sm text-muted-foreground">Redirecting to your dashboard…</p>
          </>
        )}
        {state === 'error' && (
          <>
            <p className="text-lg font-medium text-destructive">Link expired or invalid</p>
            <p className="text-sm text-muted-foreground">{errorMsg}</p>
            <a href="/login" className="text-sm text-primary underline-offset-2 hover:underline">
              Request a new link
            </a>
          </>
        )}
      </div>
    </div>
  )
}
