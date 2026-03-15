import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { adminGetEventsDashboard } from '@/lib/api'
import type { FunnelStep, WeeklyRow } from '@/lib/types'

// Consistent colors for event types in recharts
const EVENT_COLORS: Record<string, string> = {
  email_sent:       '#94a3b8',
  email_open:       '#60a5fa',
  link_clicked:     '#34d399',
  subscribe_clicked:'#f59e0b',
  signup_completed: '#6366f1',
}

function FunnelBar({ step }: { step: FunnelStep }) {
  const pct = step.conversion_rate
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{step.event_type}</span>
        <span className="text-muted-foreground tabular-nums">
          {step.count.toLocaleString()} · {pct}%
        </span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${Math.max(pct, pct > 0 ? 1 : 0)}%` }}
        />
      </div>
    </div>
  )
}

function weeklyToChartData(weekly: WeeklyRow[]) {
  return weekly.map(row => ({
    week: row.week.slice(5), // "MM-DD"
    ...row.counts,
  }))
}

export default function AdminEventsDashboard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-events-dashboard'],
    queryFn:  () => adminGetEventsDashboard(8),
  })

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (isError || !data) return <p className="text-sm text-destructive">Failed to load dashboard.</p>

  const { funnel, weekly, user_statuses, recent_conversions } = data.dashboard
  const weeklyChart = weeklyToChartData(weekly)
  const trackedTypes = ['email_sent', 'email_open', 'link_clicked', 'subscribe_clicked', 'signup_completed']

  return (
    <div className="space-y-10">
      <h1 className="text-2xl font-semibold">Events dashboard</h1>

      {/* ── Funnel ──────────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Funnel</h2>
        <div className="rounded-lg border bg-card p-6 space-y-4">
          {funnel.map(step => (
            <FunnelBar key={step.event_type} step={step} />
          ))}
          <p className="text-xs text-muted-foreground pt-1">
            Conversion rates relative to email_sent. Last 8 weeks.
          </p>
        </div>
      </section>

      {/* ── Weekly chart ────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Weekly activity</h2>
        <div className="rounded-lg border bg-card p-6">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={weeklyChart} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="week" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{ fontSize: 12 }}
                cursor={{ fill: 'var(--color-muted)' }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {trackedTypes.map(t => (
                <Bar key={t} dataKey={t} fill={EVENT_COLORS[t] ?? '#94a3b8'} stackId="a" />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* ── User status breakdown ────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">User statuses</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {Object.entries(user_statuses)
            .sort(([, a], [, b]) => b - a)
            .map(([status, count]) => (
              <div key={status} className="rounded-lg border bg-card p-4 text-center space-y-1">
                <p className="text-2xl font-bold tabular-nums">{count}</p>
                <p className="text-xs text-muted-foreground">{status}</p>
              </div>
            ))}
        </div>
      </section>

      {/* ── Recent conversions ───────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Recent conversions</h2>
        {recent_conversions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No conversions yet.</p>
        ) : (
          <div className="rounded-lg border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Email</th>
                  <th className="px-4 py-2 text-left font-medium">Converted at</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {recent_conversions.map((c, i) => (
                  <tr key={i} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-2">{c.email || c.user_id}</td>
                    <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                      {c.converted_at.slice(0, 19).replace('T', ' ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
