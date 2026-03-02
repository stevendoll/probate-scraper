import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getMe, patchMe } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

export default function Account() {
  const qc = useQueryClient()
  const { data: user, isLoading } = useQuery({ queryKey: ['me'], queryFn: getMe })
  const [email, setEmail] = useState('')
  const [saved, setSaved] = useState(false)

  const mutation = useMutation({
    mutationFn: (e: string) => patchMe({ email: e }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['me'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  if (isLoading || !user) {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    mutation.mutate(email || user!.email)
  }

  return (
    <div className="space-y-6 max-w-lg">
      <h1 className="text-2xl font-semibold">Account</h1>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>Update your email address.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                defaultValue={user.email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            {mutation.isError && (
              <p className="text-sm text-destructive">
                {mutation.error instanceof Error ? mutation.error.message : 'Update failed'}
              </p>
            )}
            {saved && <p className="text-sm text-green-600">Saved!</p>}
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Subscription</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Status</span>
            <Badge variant={user.status === 'active' ? 'default' : 'outline'}>{user.status}</Badge>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">Counties</span>
            <span>{user.locationCodes.length > 0 ? user.locationCodes.join(', ') : '—'}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
