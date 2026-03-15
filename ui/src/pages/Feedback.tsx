import { FeedbackWidget } from '@/components/feedback-widget'

export default function Feedback() {
  return (
    <div className="py-20 px-4">
      <div className="mx-auto max-w-lg space-y-8">
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">Send feedback</h1>
          <p className="text-muted-foreground">
            Questions, ideas, or bug reports — we read everything.
          </p>
        </div>
        <FeedbackWidget source="feedback-page" />
      </div>
    </div>
  )
}
