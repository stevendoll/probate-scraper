'use client'

import { use, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminGetUser, adminPatchUser } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const VALID_STATUSES = ['active', 'inactive', 'canceled', 'past_due', 'trialing'] as const
const VALID_ROLES = ['user', 'admin'] as const

export default function AdminUserDetailPage({
  params,
}: {
  params: Promise<{ userId: string }>
}) {
  const { userId } = use(params)
  const router = useRouter()
  const qc = useQueryClient()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-user', userId],
    queryFn: () => adminGetUser(userId),
  })

  const user = data?.user

  const [status, setStatus] = useState('')
  const [role, setRole] = useState('')
  const [locationInput, setLocationInput] = useState('')

  const patch = useMutation({
    mutationFn: (update: { status?: string; role?: string; location_codes?: string[] }) =>
      adminPatchUser(userId, update),
    onSuccess: (res) => {
      qc.setQueryData(['admin-user', userId], res)
      qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
  })

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (isError || !user) return <p className="text-sm text-destructive">User not found.</p>

  const currentStatus = status || user.status
  const currentRole = role || user.role

  return (
    <div className="max-w-lg space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          ← Back
        </Button>
        <h1 className="text-2xl font-semibold truncate">{user.email}</h1>
      </div>

      {patch.isError && (
        <p className="text-sm text-destructive">
          {patch.error instanceof Error ? patch.error.message : 'Save failed'}
        </p>
      )}
      {patch.isSuccess && (
        <p className="text-sm text-green-600">Saved.</p>
      )}

      {/* Status + Role */}
      <Card>
        <CardHeader><CardTitle>Access</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <Label>Status</Label>
              <Select value={currentStatus} onValueChange={setStatus}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {VALID_STATUSES.map((s) => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Role</Label>
              <Select value={currentRole} onValueChange={setRole}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {VALID_ROLES.map((r) => (
                    <SelectItem key={r} value={r}>{r}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <Button
            size="sm"
            disabled={patch.isPending}
            onClick={() =>
              patch.mutate({
                status: currentStatus !== user.status ? currentStatus : undefined,
                role: currentRole !== user.role ? currentRole : undefined,
              })
            }
          >
            {patch.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </CardContent>
      </Card>

      {/* Counties */}
      <Card>
        <CardHeader><CardTitle>Counties</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-1">
            {user.locationCodes.length > 0
              ? user.locationCodes.map((c) => (
                  <Badge key={c} variant="secondary">{c}</Badge>
                ))
              : <span className="text-sm text-muted-foreground">None</span>}
          </div>
          <Separator />
          <div className="flex gap-2">
            <Input
              placeholder="CollinTx, DallasTx…"
              value={locationInput}
              onChange={(e) => setLocationInput(e.target.value)}
              className="flex-1"
            />
            <Button
              size="sm"
              variant="outline"
              disabled={patch.isPending || !locationInput.trim()}
              onClick={() => {
                const codes = locationInput.split(',').map((s) => s.trim()).filter(Boolean)
                patch.mutate({ location_codes: codes })
                setLocationInput('')
              }}
            >
              Replace
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Enter comma-separated location codes to replace the current list.
          </p>
        </CardContent>
      </Card>

      {/* Info */}
      <Card>
        <CardHeader><CardTitle>Info</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">User ID</span>
            <span className="font-mono text-xs">{user.userId}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Stripe customer</span>
            <span className="font-mono text-xs">{user.stripeCustomerId || '—'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Created</span>
            <span>{user.createdAt.slice(0, 10)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Updated</span>
            <span>{user.updatedAt.slice(0, 10)}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
