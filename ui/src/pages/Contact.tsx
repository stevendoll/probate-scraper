import { FeedbackWidget } from '@/components/feedback-widget'

const faqs = [
  {
    q: 'What counties are covered?',
    a: 'Currently Collin County, Texas. Additional counties are planned — use the feedback form below to tell us which county you need next.',
  },
  {
    q: 'How often are leads updated?',
    a: 'The scraper runs every day. New filings appear in your dashboard the morning after they are recorded at the courthouse.',
  },
  {
    q: 'How accurate is the AI extraction?',
    a: 'We use Amazon Bedrock Nova Pro to parse each PDF. Accuracy is high for well-structured documents; we recommend reviewing contacts before outreach for any unusual filings.',
  },
  {
    q: 'Can I cancel my subscription?',
    a: 'Yes — cancel any time from your Account page. Your access continues until the end of the billing period.',
  },
  {
    q: 'Is this legal to use?',
    a: 'Yes. Probate filings are public court records. We only collect and display information that is already publicly available at the courthouse.',
  },
]

export default function Contact() {
  return (
    <div className="py-20 px-4">
      <div className="mx-auto max-w-2xl space-y-16">
        {/* Header */}
        <div className="text-center space-y-2">
          <h1 className="text-4xl font-bold tracking-tight">Contact & FAQ</h1>
          <p className="text-muted-foreground">
            Common questions and a direct line to the team.
          </p>
        </div>

        {/* FAQ */}
        <section className="space-y-4">
          <h2 className="text-xl font-semibold">Frequently asked questions</h2>
          <div className="divide-y rounded-lg border overflow-hidden">
            {faqs.map(({ q, a }) => (
              <details key={q} className="group bg-card">
                <summary className="flex cursor-pointer select-none items-center justify-between px-4 py-3 text-sm font-medium list-none hover:bg-muted/50 transition-colors">
                  {q}
                  <span className="ml-4 shrink-0 text-muted-foreground group-open:rotate-180 transition-transform">
                    ▾
                  </span>
                </summary>
                <p className="px-4 pb-4 pt-1 text-sm text-muted-foreground leading-relaxed">
                  {a}
                </p>
              </details>
            ))}
          </div>
        </section>

        {/* Direct contact */}
        <section className="space-y-2">
          <h2 className="text-xl font-semibold">Email us</h2>
          <p className="text-sm text-muted-foreground">
            Reach the team directly at{' '}
            <a
              href="mailto:hello@collincountyleads.com"
              className="text-primary hover:underline"
            >
              hello@collincountyleads.com
            </a>
          </p>
        </section>

        {/* Feedback widget */}
        <section className="space-y-4">
          <FeedbackWidget title="Talk to us" source="contact-page" />
        </section>
      </div>
    </div>
  )
}
