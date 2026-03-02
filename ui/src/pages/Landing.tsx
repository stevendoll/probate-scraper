import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

export default function Landing() {
  return (
    <div className="min-h-screen bg-background">
      {/* Nav */}
      <header className="border-b">
        <div className="mx-auto max-w-5xl flex items-center justify-between h-14 px-4">
          <span className="font-semibold text-lg tracking-tight">Probate Leads</span>
          <nav className="flex items-center gap-4">
            <Link to="/login" className="text-sm text-muted-foreground hover:text-foreground">
              Sign in
            </Link>
            <Button asChild size="sm">
              <Link to="/login">Get started</Link>
            </Button>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-3xl px-4 py-24 text-center space-y-6">
        <Badge variant="secondary">Daily updates · Collin County TX</Badge>
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Fresh probate records,
          <br />
          delivered daily
        </h1>
        <p className="text-lg text-muted-foreground max-w-xl mx-auto">
          Automatically scraped, parsed, and ready to export. Get notified the moment new
          probate filings match your counties — before your competitors see them.
        </p>
        <div className="flex gap-3 justify-center">
          <Button asChild size="lg">
            <Link to="/login">Start free trial</Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <a href="#features">Learn more</a>
          </Button>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="border-t">
        <div className="mx-auto max-w-5xl px-4 py-16 grid sm:grid-cols-3 gap-8">
          {[
            {
              title: 'Daily scrapes',
              desc: 'New filings pulled every morning at 6 AM UTC from the county recorder.',
            },
            {
              title: 'AI-parsed details',
              desc: 'Deceased name, DOB, DOD, property descriptions, and heir info extracted by Amazon Bedrock.',
            },
            {
              title: 'Secure access',
              desc: 'Passwordless magic-link login. No passwords to remember or rotate.',
            },
          ].map((f) => (
            <div key={f.title} className="space-y-2">
              <h3 className="font-semibold">{f.title}</h3>
              <p className="text-sm text-muted-foreground">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t">
        <div className="mx-auto max-w-5xl px-4 py-6 text-center text-xs text-muted-foreground">
          © {new Date().getFullYear()} Probate Leads. All rights reserved.
        </div>
      </footer>
    </div>
  )
}
