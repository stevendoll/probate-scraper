import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { MapPin, Clock, FileText } from 'lucide-react'

const features = [
  {
    icon: MapPin,
    title: 'Collin County coverage',
    description: 'Every probate filing recorded at the Collin County courthouse — scraped daily so you never miss a new case.',
  },
  {
    icon: Clock,
    title: 'Updated daily',
    description: 'Fresh leads each morning. Be the first to reach executors and heirs before other investors know the case exists.',
  },
  {
    icon: FileText,
    title: 'AI-extracted contacts',
    description: 'Deceased name, executor, attorney, and property address extracted and structured — ready to use in your outreach.',
  },
]

export default function Landing() {
  return (
    <div className="flex flex-col">
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="py-24 px-4 text-center bg-gradient-to-b from-secondary/60 to-background">
        <div className="mx-auto max-w-2xl space-y-6">
          <h1 className="text-5xl font-bold tracking-tight leading-tight">
            Probate leads,<br />delivered daily
          </h1>
          <p className="text-xl text-muted-foreground max-w-lg mx-auto">
            Get every Collin County probate filing in your inbox — with AI-extracted
            contact info so you can reach heirs before anyone else.
          </p>
          <div className="flex flex-wrap justify-center gap-3 pt-2">
            <Button asChild size="lg" className="text-base px-8">
              <Link to="/login">Get started</Link>
            </Button>
            <Button asChild size="lg" variant="outline" className="text-base px-8">
              <Link to="/how-it-works">How it works</Link>
            </Button>
          </div>
        </div>
      </section>

      {/* ── Social proof strip ───────────────────────────────────────────── */}
      <div className="border-y bg-muted/40 py-3 text-center">
        <p className="text-sm text-muted-foreground">
          Updated daily from Collin County courthouse records · AI-parsed contacts & property addresses
        </p>
      </div>

      {/* ── Features grid ────────────────────────────────────────────────── */}
      <section className="py-20 px-4">
        <div className="mx-auto max-w-4xl">
          <h2 className="text-2xl font-semibold text-center mb-12">
            Everything you need to find motivated sellers
          </h2>
          <div className="grid sm:grid-cols-3 gap-8">
            {features.map(({ icon: Icon, title, description }) => (
              <div key={title} className="flex flex-col items-start gap-3">
                <div className="rounded-lg bg-primary/10 p-2.5">
                  <Icon className="h-5 w-5 text-primary" />
                </div>
                <h3 className="font-semibold">{title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA footer ───────────────────────────────────────────────────── */}
      <section className="py-16 px-4 text-center bg-primary/5 border-t">
        <div className="mx-auto max-w-lg space-y-4">
          <h2 className="text-2xl font-semibold">Ready to find your next deal?</h2>
          <p className="text-muted-foreground text-sm">
            Join investors who get Collin County probate leads delivered to their inbox every morning.
          </p>
          <Button asChild size="lg" className="mt-2">
            <Link to="/login">Start now</Link>
          </Button>
        </div>
      </section>
    </div>
  )
}
