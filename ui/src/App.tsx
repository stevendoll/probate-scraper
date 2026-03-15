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
import DocumentDetail from '@/pages/DocumentDetail'
import HowItWorks from '@/pages/HowItWorks'
import Contact from '@/pages/Contact'
import Feedback from '@/pages/Feedback'
import AdminUsers from '@/pages/admin/Users'
import AdminUserDetail from '@/pages/admin/UserDetail'
import AdminProspectSend from '@/pages/admin/ProspectSend'
import AdminEvents from '@/pages/admin/Events'
import AdminEventsDashboard from '@/pages/admin/EventsDashboard'

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

/** Shared nav link style */
const navLink = 'text-sm text-muted-foreground hover:text-foreground transition-colors'

/**
 * CustomerLayout — shown for authenticated user pages.
 * Nav: brand + Dashboard + Account
 */
function CustomerLayout() {
  const { data: user } = useQuery({ queryKey: ['me'], queryFn: getMe })
  const nav = useNavigate()
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b bg-card/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <nav className="flex items-center gap-6">
            <Link to="/" className="font-semibold text-base tracking-tight text-foreground">
              Collin County Leads
            </Link>
            <Link to="/dashboard" className={navLink}>Dashboard</Link>
            <Link to="/account" className={navLink}>Account</Link>
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

/**
 * PublicLayout — wraps public marketing pages (Landing, HowItWorks, Contact, Feedback).
 * Same brand nav but without auth-only links.
 */
function PublicLayout() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b bg-card/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <nav className="flex items-center gap-6">
            <Link to="/" className="font-semibold text-base tracking-tight text-foreground">
              Collin County Leads
            </Link>
            <Link to="/how-it-works" className={navLink}>How it works</Link>
            <Link to="/contact" className={navLink}>Contact</Link>
          </nav>
          <Link to="/login" className="text-sm font-medium text-primary hover:underline">
            Sign in
          </Link>
        </div>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}

/**
 * AdminLayout — shown for admin-only pages.
 * Same shared theme; wider nav with Events, Dashboard, Users, Prospects links.
 */
function AdminLayout() {
  const { data: user } = useQuery({ queryKey: ['me'], queryFn: getMe })
  const nav = useNavigate()
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b bg-card/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <nav className="flex items-center gap-6">
            <Link to="/admin/users" className="font-semibold text-base tracking-tight text-foreground">
              Collin County Leads{' '}
              <span className="text-muted-foreground font-normal text-sm">Admin</span>
            </Link>
            <Link to="/admin/events/dashboard" className={navLink}>Dashboard</Link>
            <Link to="/admin/events" className={navLink}>Events</Link>
            <Link to="/admin/users" className={navLink}>Users</Link>
            <Link to="/admin/prospect/send" className={navLink}>Prospects</Link>
            <Link to="/dashboard" className={navLink}>My dashboard</Link>
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
          {/* Public marketing pages */}
          <Route element={<PublicLayout />}>
            <Route path="/" element={<Landing />} />
            <Route path="/how-it-works" element={<HowItWorks />} />
            <Route path="/contact" element={<Contact />} />
            <Route path="/feedback" element={<Feedback />} />
          </Route>

          {/* Auth flows — no layout */}
          <Route path="/login" element={<Login />} />
          <Route path="/auth/verify" element={<AuthVerify />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/unsubscribe" element={<Unsubscribe />} />

          {/* Authenticated customer pages */}
          <Route element={<ProtectedRoute />}>
            <Route element={<CustomerLayout />}>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/account" element={<Account />} />
              <Route path="/documents/:documentId" element={<DocumentDetail />} />
            </Route>
          </Route>

          {/* Admin-only pages */}
          <Route element={<ProtectedRoute requireAdmin />}>
            <Route element={<AdminLayout />}>
              <Route path="/admin/users" element={<AdminUsers />} />
              <Route path="/admin/users/:userId" element={<AdminUserDetail />} />
              <Route path="/admin/prospect/send" element={<AdminProspectSend />} />
              <Route path="/admin/events" element={<AdminEvents />} />
              <Route path="/admin/events/dashboard" element={<AdminEventsDashboard />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryProvider>
  )
}
