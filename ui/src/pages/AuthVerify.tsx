import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { verifyMagicToken } from '@/lib/api'
import { setToken } from '@/lib/auth'

type State = 'verifying' | 'success' | 'error'

export default function AuthVerify() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [state, setState] = useState<State>('verifying')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    const token = searchParams.get('token')
    if (!token) {
      setState('error')
      setErrorMsg('No token found in the link.')
      return
    }

    verifyMagicToken(token)
      .then((data) => {
        setToken(data.accessToken)
        setState('success')
        const dest = data.user.role === 'admin' ? '/admin/users' : '/dashboard'
        navigate(dest, { replace: true })
      })
      .catch((err) => {
        setState('error')
        setErrorMsg(err instanceof Error ? err.message : 'Invalid or expired link.')
      })
  }, [searchParams, navigate])

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
