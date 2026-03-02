import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { verifyMagicToken } from '@/lib/api'
import { setToken } from '@/lib/auth'

export default function AuthVerify() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState('')

  useEffect(() => {
    const token = searchParams.get('token')
    if (!token) {
      setError('No token provided.')
      return
    }

    verifyMagicToken(token)
      .then((data) => {
        setToken(data.accessToken)
        const dest = data.user.role === 'admin' ? '/admin/users' : '/dashboard'
        navigate(dest, { replace: true })
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Verification failed')
      })
  }, [searchParams, navigate])

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 px-4 text-center">
        <p className="text-destructive">{error}</p>
        <a href="/login" className="text-sm text-primary underline underline-offset-2">
          Back to login
        </a>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <p className="text-muted-foreground text-sm">Verifying your link…</p>
    </div>
  )
}
