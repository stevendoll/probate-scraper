import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { adminListUsers } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export default function AdminUsers() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: adminListUsers,
  })

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Users</h1>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p className="text-sm text-destructive">Failed to load users.</p>}

      {data && (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Counties</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.users.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                    No users found.
                  </TableCell>
                </TableRow>
              )}
              {data.users.map((user) => (
                <TableRow key={user.userId}>
                  <TableCell>
                    {user.firstName || user.lastName 
                      ? `${user.firstName || ''} ${user.lastName || ''}`.trim() 
                      : '—'
                    }
                  </TableCell>
                  <TableCell>{user.email}</TableCell>
                  <TableCell className="capitalize">{user.role}</TableCell>
                  <TableCell>
                    <Badge variant={user.status === 'active' ? 'default' : 'outline'}>
                      {user.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{user.locationCodes.join(', ') || '—'}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                    {new Date(user.createdAt).toLocaleDateString()}
                  </TableCell>
                  <TableCell>
                    <Link
                      to={`/admin/users/${user.userId}`}
                      className="text-xs text-primary hover:underline underline-offset-2"
                    >
                      Edit
                    </Link>
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
