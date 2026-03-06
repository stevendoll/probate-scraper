import { BrowserRouter, Routes, Route, Navigate, Outlet, Link } from 'react-router-dom'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { QueryProvider } from '@/components/query-provider'
import { UserNav } from '@/components/user-nav'
import { useAuth } from '@/lib/auth'
import { getMe } from '@/lib/api'

import Landing from '@/pages/Landing'
import Login from '@/pages/Login'
import AuthVerify from '@/pages/AuthVerify'
import Signup from '@/pages/Signup'
import Unsubscribe from '@/pages/Unsubscribe'
import Dashboard from '@/pages/Dashboard'
import Account from '@/pages/Account'
import AdminUsers from '@/pages/admin/Users'
import AdminUserDetail from '@/pages/admin/UserDetail'
import AdminProspectSend from '@/pages/admin/ProspectSend'

// ---------------------------------------------------------------------------
// Guards
// ---------------------------------------------------------------------------

function ProtectedRoute({ requireAdmin = false }: { requireAdmin?: boolean }) {
  const { token, payload } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  if (requireAdmin && payload?.role !== 'admin') return <Navigate to="/dashboard" replace />
  return <Outlet />
}

// ---------------------------------------------------------------------------
// Layouts
// ---------------------------------------------------------------------------

function UserLayout() {
  const { data: user } = useQuery({ queryKey: ['me'], queryFn: getMe })
  const nav = useNavigate()
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <nav className="flex items-center gap-6">
            <Link to="/dashboard" className="font-semibold text-lg tracking-tight">
              Probate Leads
            </Link>
            <Link to="/dashboard" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              Dashboard
            </Link>
            <Link to="/account" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              Account
            </Link>
          </nav>
          {user && <UserNav user={user} navigate={nav} />}
        </div>
      </header>
      <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

function AdminLayout() {
  const { data: user } = useQuery({ queryKey: ['me'], queryFn: getMe })
  const nav = useNavigate()
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b bg-muted/40">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <nav className="flex items-center gap-6">
            <Link to="/admin/users" className="font-semibold text-lg tracking-tight">
              Probate Leads{' '}
              <span className="text-muted-foreground font-normal text-sm">Admin</span>
            </Link>
            <Link to="/admin/users" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              Users
            </Link>
            <Link to="/admin/prospect/send" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              Prospects
            </Link>
            <Link to="/dashboard" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
              My dashboard
            </Link>
          </nav>
          {user && <UserNav user={user} navigate={nav} />}
        </div>
      </header>
      <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  return (
    <QueryProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/auth/verify" element={<AuthVerify />} />

          {/* Public prospect pages — no auth required */}
          <Route path="/signup" element={<Signup />} />
          <Route path="/unsubscribe" element={<Unsubscribe />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<UserLayout />}>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/account" element={<Account />} />
            </Route>
          </Route>

          <Route element={<ProtectedRoute requireAdmin />}>
            <Route element={<AdminLayout />}>
              <Route path="/admin/users" element={<AdminUsers />} />
              <Route path="/admin/users/:userId" element={<AdminUserDetail />} />
              <Route path="/admin/prospect/send" element={<AdminProspectSend />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryProvider>
  )
}
