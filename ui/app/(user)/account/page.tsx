'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getMe, patchMe } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'

export default function AccountPage() {
  const qc = useQueryClient()
  const { data: user, isLoading } = useQuery({ queryKey: ['me'], queryFn: getMe })

  const [email, setEmail] = useState('')
  const [editing, setEditing] = useState(false)

  const updateEmail = useMutation({
    mutationFn: (newEmail: string) => patchMe({ email: newEmail }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['me'] })
      setEditing(false)
    },
  })

  if (isLoading || !user) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }

  const statusColor: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
    active: 'default',
    trialing: 'secondary',
    past_due: 'destructive',
    canceled: 'outline',
    inactive: 'outline',
  }

  return (
    <div className="max-w-lg space-y-6">
      <h1 className="text-2xl font-semibold">Account</h1>

      {/* Profile */}
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>Manage your email address.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {editing ? (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                updateEmail.mutate(email)
              }}
              className="space-y-3"
            >
              <div className="space-y-1">
                <Label htmlFor="email">New email</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoFocus
                  required
                />
              </div>
              {updateEmail.isError && (
                <p className="text-sm text-destructive">
                  {updateEmail.error instanceof Error
                    ? updateEmail.error.message
                    : 'Failed to update'}
                </p>
              )}
              <div className="flex gap-2">
                <Button type="submit" size="sm" disabled={updateEmail.isPending}>
                  {updateEmail.isPending ? 'Saving…' : 'Save'}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setEditing(false)}
                >
                  Cancel
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex items-center justify-between">
              <span className="text-sm">{user.email}</span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEmail(user.email)
                  setEditing(true)
                }}
              >
                Edit
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Subscription */}
      <Card>
        <CardHeader>
          <CardTitle>Subscription</CardTitle>
          <CardDescription>Your current plan and counties.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Status</span>
            <Badge variant={statusColor[user.status] ?? 'outline'}>{user.status}</Badge>
          </div>
          <Separator />
          <div className="flex items-start justify-between">
            <span className="text-sm text-muted-foreground">Counties</span>
            <div className="flex flex-wrap gap-1 max-w-xs justify-end">
              {user.locationCodes.length > 0
                ? user.locationCodes.map((c) => (
                    <Badge key={c} variant="secondary">
                      {c}
                    </Badge>
                  ))
                : <span className="text-sm text-muted-foreground">None</span>}
            </div>
          </div>
          <Separator />
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Member since</span>
            <span className="text-sm">{user.createdAt.slice(0, 10)}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
