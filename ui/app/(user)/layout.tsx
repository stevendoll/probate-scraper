import { requireAuth } from '@/lib/auth'
import { fetchMe } from '@/lib/auth'
import { UserNav } from '@/components/user-nav'
import Link from 'next/link'

export default async function UserLayout({ children }: { children: React.ReactNode }) {
  const { token } = await requireAuth()
  const user = await fetchMe(token)

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <nav className="flex items-center gap-6">
            <Link href="/dashboard" className="font-semibold text-lg tracking-tight">
              Probate Leads
            </Link>
            <Link
              href="/dashboard"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Dashboard
            </Link>
            <Link
              href="/account"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Account
            </Link>
          </nav>
          <UserNav user={user} />
        </div>
      </header>
      <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-8">{children}</main>
    </div>
  )
}
