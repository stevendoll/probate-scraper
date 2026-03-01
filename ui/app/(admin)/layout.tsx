import { requireAdmin, fetchMe } from '@/lib/auth'
import { UserNav } from '@/components/user-nav'
import Link from 'next/link'

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const { token } = await requireAdmin()
  const user = await fetchMe(token)

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b bg-muted/40">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <nav className="flex items-center gap-6">
            <Link href="/admin/users" className="font-semibold text-lg tracking-tight">
              Probate Leads <span className="text-muted-foreground font-normal text-sm">Admin</span>
            </Link>
            <Link
              href="/admin/users"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Users
            </Link>
            <Link
              href="/dashboard"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              My dashboard
            </Link>
          </nav>
          <UserNav user={user} />
        </div>
      </header>
      <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-8">{children}</main>
    </div>
  )
}
