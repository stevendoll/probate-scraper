import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminGetUser, adminPatchUser, adminDeleteUser } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export default function AdminUserDetail() {
  const { userId } = useParams<{ userId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'users', userId],
    queryFn: () => adminGetUser(userId!),
    enabled: !!userId,
  })

  const [status, setStatus] = useState('')
  const [role, setRole] = useState('')
  const [locationCodes, setLocationCodes] = useState('')
  const [journeyType, setJourneyType] = useState('')
  const [journeyStep, setJourneyStep] = useState('')
  const [trialExpiresOn, setTrialExpiresOn] = useState('')
  const [saved, setSaved] = useState(false)

  const user = data?.user

  const patchMutation = useMutation({
    mutationFn: () =>
      adminPatchUser(userId!, {
        ...(status ? { status } : {}),
        ...(role ? { role } : {}),
        ...(locationCodes !== ''
          ? { location_codes: locationCodes.split(',').map((s) => s.trim()).filter(Boolean) }
          : {}),
        ...(journeyType ? { journey_type: journeyType } : {}),
        ...(journeyStep ? { journey_step: journeyStep } : {}),
        ...(trialExpiresOn ? { trial_expires_on: trialExpiresOn } : {}),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => adminDeleteUser(userId!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
      navigate('/admin/users')
    },
  })

  if (isLoading || !user) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }

  return (
    <div className="space-y-6 max-w-lg">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          ← Back
        </Button>
        <h1 className="text-2xl font-semibold">User detail</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{user.email}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            <span className="text-muted-foreground">Role: </span>
            <span className="capitalize">{user.role}</span>
          </p>
          <p className="flex items-center gap-2">
            <span className="text-muted-foreground">Status: </span>
            <Badge variant={user.status === 'active' ? 'default' : 'outline'}>{user.status}</Badge>
          </p>
          <p>
            <span className="text-muted-foreground">Counties: </span>
            {user.locationCodes.join(', ') || '—'}
          </p>
          {user.journeyType && (
            <p>
              <span className="text-muted-foreground">Journey: </span>
              <span className="capitalize">{user.journeyType.replace('_', ' ')}</span>
              {user.journeyStep && ` → ${user.journeyStep.replace('_', ' ')}`}
            </p>
          )}
          {user.trialExpiresOn && (
            <p>
              <span className="text-muted-foreground">Trial expires: </span>
              {new Date(user.trialExpiresOn).toLocaleDateString()}
            </p>
          )}
          {user.stripeCustomerId && (
            <p>
              <span className="text-muted-foreground">Stripe customer: </span>
              <span className="font-mono text-xs">{user.stripeCustomerId}</span>
            </p>
          )}
          <p>
            <span className="text-muted-foreground">Created: </span>
            {new Date(user.createdAt).toLocaleDateString()}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Edit</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Status</Label>
            <Select onValueChange={setStatus} defaultValue={user.status}>
              <SelectTrigger>
                <SelectValue placeholder="Select status" />
              </SelectTrigger>
              <SelectContent>
                {[
                  'active', 'inactive', 'past_due', 'canceled', 'trialing', 'free_trial',
                  'unsubscribed', 'prospect', 'inbound',
                  'invited_to_waitlist', 'accepted_waitlist', 'invited_to_join',
                  'invited_to_trial', 'trial_expired'
                ].map((s) => (
                  <SelectItem key={s} value={s}>
                    {s.replace(/_/g, ' ')}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Role</Label>
            <Select onValueChange={setRole} defaultValue={user.role}>
              <SelectTrigger>
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">user</SelectItem>
                <SelectItem value="admin">admin</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="counties">Counties (comma-separated)</Label>
            <Input
              id="counties"
              placeholder={user.locationCodes.join(', ') || 'e.g. CollinTx, DallasTx'}
              onChange={(e) => setLocationCodes(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label>Journey Type</Label>
            <Select onValueChange={setJourneyType} defaultValue={user.journeyType}>
              <SelectTrigger>
                <SelectValue placeholder="Select journey type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">None</SelectItem>
                <SelectItem value="prospect">Prospect</SelectItem>
                <SelectItem value="coming_soon">Coming Soon</SelectItem>
                <SelectItem value="free_trial">Free Trial</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Journey Step</Label>
            <Select onValueChange={setJourneyStep} defaultValue={user.journeyStep}>
              <SelectTrigger>
                <SelectValue placeholder="Select journey step" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">None</SelectItem>
                <SelectItem value="prospect">Prospect</SelectItem>
                <SelectItem value="inbound">Inbound</SelectItem>
                <SelectItem value="invited_to_waitlist">Invited to Waitlist</SelectItem>
                <SelectItem value="accepted_waitlist">Accepted Waitlist</SelectItem>
                <SelectItem value="invited_to_join">Invited to Join</SelectItem>
                <SelectItem value="invited_to_trial">Invited to Trial</SelectItem>
                <SelectItem value="trialing">Trialing</SelectItem>
                <SelectItem value="trial_expired">Trial Expired</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="trialExpires">Trial Expires (ISO date)</Label>
            <Input
              id="trialExpires"
              type="datetime-local"
              placeholder={user.trialExpiresOn || 'YYYY-MM-DDTHH:MM:SS'}
              onChange={(e) => {
                // Convert datetime-local to ISO string
                const isoString = e.target.value ? new Date(e.target.value).toISOString() : ''
                setTrialExpiresOn(isoString)
              }}
            />
            {user.trialExpiresOn && (
              <p className="text-xs text-muted-foreground">
                Current: {new Date(user.trialExpiresOn).toLocaleString()}
              </p>
            )}
          </div>

          {patchMutation.isError && (
            <p className="text-sm text-destructive">
              {patchMutation.error instanceof Error ? patchMutation.error.message : 'Update failed'}
            </p>
          )}
          {saved && <p className="text-sm text-green-600">Saved!</p>}

          <div className="flex gap-2">
            <Button onClick={() => patchMutation.mutate()} disabled={patchMutation.isPending}>
              {patchMutation.isPending ? 'Saving…' : 'Save'}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (confirm(`Deactivate ${user.email}?`)) deleteMutation.mutate()
              }}
              disabled={deleteMutation.isPending}
            >
              Deactivate
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
