import { LoginForm } from '@/components/login-form'

export const metadata = { title: 'Sign in — Probate Leads' }

export default function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
          <p className="text-sm text-muted-foreground">
            Enter your email and we&apos;ll send you a magic link.
          </p>
        </div>
        <LoginForm />
      </div>
    </div>
  )
}
