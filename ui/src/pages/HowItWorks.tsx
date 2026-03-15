import { Building2, Cpu, Mail } from 'lucide-react'

const steps = [
  {
    number: 1,
    icon: Building2,
    title: 'County records filed',
    description:
      'Every day families file probate cases at the Collin County courthouse. These filings are public record — but manually checking them is slow and inconsistent.',
  },
  {
    number: 2,
    icon: Cpu,
    title: 'AI extracts contacts & property',
    description:
      'Our scraper captures every new filing and runs it through AI to pull out the deceased name, executor, attorney, and any real-estate addresses — structured and ready to use.',
  },
  {
    number: 3,
    icon: Mail,
    title: 'You reach out first',
    description:
      'Fresh leads land in your dashboard each morning. Search by date, browse contacts, and start outreach before other investors even know the case was filed.',
  },
]

export default function HowItWorks() {
  return (
    <div className="py-20 px-4">
      <div className="mx-auto max-w-3xl space-y-16">
        {/* Header */}
        <div className="text-center space-y-3">
          <h1 className="text-4xl font-bold tracking-tight">How it works</h1>
          <p className="text-muted-foreground text-lg max-w-xl mx-auto">
            From courthouse filing to your outreach list — automated, every day.
          </p>
        </div>

        {/* Steps */}
        <ol className="space-y-12">
          {steps.map(({ number, icon: Icon, title, description }) => (
            <li key={number} className="flex gap-6">
              <div className="flex-shrink-0 flex flex-col items-center gap-2">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-primary-foreground font-bold text-sm">
                  {number}
                </div>
                {number < steps.length && (
                  <div className="w-px flex-1 bg-border min-h-[2rem]" />
                )}
              </div>
              <div className="pb-4 space-y-2">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-primary" />
                  <h2 className="font-semibold text-lg">{title}</h2>
                </div>
                <p className="text-muted-foreground leading-relaxed">{description}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
