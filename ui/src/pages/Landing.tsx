import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export default function Landing() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 px-4 text-center">
      <div className="space-y-2">
        <h1 className="text-4xl font-bold tracking-tight">Probate Leads</h1>
        <p className="text-lg text-muted-foreground max-w-md">
          Daily probate filings from Texas county courthouses, delivered to your inbox.
        </p>
      </div>
      <Button asChild size="lg">
        <Link to="/login">Get started</Link>
      </Button>
    </div>
  )
}
