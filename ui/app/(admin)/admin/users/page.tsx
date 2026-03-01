'use client'

import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminListUsers, adminDeleteUser } from '@/lib/api'
import type { User } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useState } from 'react'

const statusVariant: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  active: 'default',
  trialing: 'secondary',
  past_due: 'destructive',
  canceled: 'outline',
  inactive: 'outline',
}

export default function AdminUsersPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin-users'],
    queryFn: adminListUsers,
  })

  const softDelete = useMutation({
    mutationFn: adminDeleteUser,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  const users: User[] = (data?.users ?? []).filter((u) =>
    search ? u.email.toLowerCase().includes(search.toLowerCase()) : true,
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Users</h1>
        <span className="text-sm text-muted-foreground">{data?.count ?? 0} total</span>
      </div>

      <Input
        placeholder="Search by email…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="max-w-xs"
      />

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p className="text-sm text-destructive">Failed to load users.</p>}

      {data && (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Counties</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    No users found.
                  </TableCell>
                </TableRow>
              )}
              {users.map((u) => (
                <TableRow key={u.userId}>
                  <TableCell className="font-medium">{u.email}</TableCell>
                  <TableCell>
                    <Badge variant={u.role === 'admin' ? 'default' : 'outline'}>
                      {u.role}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusVariant[u.status] ?? 'outline'}>{u.status}</Badge>
                  </TableCell>
                  <TableCell className="text-sm">
                    {u.locationCodes.join(', ') || '—'}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                    {u.createdAt.slice(0, 10)}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button asChild variant="ghost" size="sm">
                        <Link href={`/admin/users/${u.userId}`}>Edit</Link>
                      </Button>
                      {u.status !== 'inactive' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          disabled={softDelete.isPending}
                          onClick={() => {
                            if (confirm(`Deactivate ${u.email}?`)) {
                              softDelete.mutate(u.userId)
                            }
                          }}
                        >
                          Deactivate
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
