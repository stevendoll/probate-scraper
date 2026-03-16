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
const navLink      = 'text-sm text-muted-foreground hover:text-foreground transition-colors'
/** Admin nav link style — violet to distinguish from user links */
const adminNavLink = 'text-sm text-violet-500 hover:text-violet-700 dark:text-violet-400 dark:hover:text-violet-300 transition-colors'

/**
 * AppLayout — single authenticated layout for both customer and admin pages.
 * User links (Dashboard, Account) sit on the left; if the user is an admin,
 * admin links (Analytics, Events, Users, Prospects) follow in violet after a
 * thin separator.
 */
function AppLayout() {
  const { data: user } = useQuery({ queryKey: ['me'], queryFn: getMe })
  const nav = useNavigate()
  const isAdmin = user?.role === 'admin'

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b bg-card/80 backdrop-blur-sm sticky top-0 z-40">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <nav className="flex items-center gap-6">
            {/* ── User links ── */}
            <Link to="/dashboard" className="font-semibold text-base tracking-tight text-foreground">
              Collin County Leads
            </Link>
            <Link to="/dashboard"    className={navLink}>Dashboard</Link>
            <Link to="/account"      className={navLink}>Account</Link>
            <Link to="/how-it-works" className={navLink}>How it works</Link>
            <Link to="/contact"      className={navLink}>Contact</Link>

            {/* ── Admin links (admins only) ── */}
            {isAdmin && (
              <>
                <span className="h-4 w-px bg-border" aria-hidden="true" />
                <Link to="/admin/events/dashboard" className={adminNavLink}>Analytics</Link>
                <Link to="/admin/events"           className={adminNavLink}>Events</Link>
                <Link to="/admin/users"            className={adminNavLink}>Users</Link>
                <Link to="/admin/prospect/send"    className={adminNavLink}>Prospects</Link>
              </>
            )}
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
            <Link to="/contact"      className={navLink}>Contact</Link>
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

          {/* Authenticated pages — single layout for users and admins */}
          <Route element={<ProtectedRoute />}>
            <Route element={<AppLayout />}>
              {/* Customer routes */}
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/account" element={<Account />} />
              <Route path="/documents/:documentId" element={<DocumentDetail />} />

              {/* Admin-only routes — nested guard */}
              <Route element={<ProtectedRoute requireAdmin />}>
                <Route path="/admin/users" element={<AdminUsers />} />
                <Route path="/admin/users/:userId" element={<AdminUserDetail />} />
                <Route path="/admin/prospect/send" element={<AdminProspectSend />} />
                <Route path="/admin/events" element={<AdminEvents />} />
                <Route path="/admin/events/dashboard" element={<AdminEventsDashboard />} />
              </Route>
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryProvider>
  )
}
