import { useSearchParams, Link } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { CheckCircle2, Clock, Mail, ArrowRight } from 'lucide-react'

export default function WaitlistSuccess() {
  const [searchParams] = useSearchParams()
  const email = searchParams.get('email') || 'your email'

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-lg w-full space-y-6">
        {/* Success Header */}
        <div className="text-center space-y-4">
          <div className="flex justify-center">
            <div className="rounded-full bg-green-100 dark:bg-green-900 p-4">
              <CheckCircle2 className="h-12 w-12 text-green-600 dark:text-green-400" />
            </div>
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              You're on the waitlist!
            </h1>
            <p className="text-muted-foreground mt-2">
              Thanks for your interest in Collin County Probate Leads
            </p>
          </div>
        </div>

        {/* Confirmation Details */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Mail className="h-5 w-5 text-blue-500" />
              Confirmation sent
            </CardTitle>
            <CardDescription>
              We've sent a confirmation email to <span className="font-medium">{email}</span>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="rounded-lg bg-muted p-4">
                <h4 className="font-medium text-sm mb-3">What happens next?</h4>
                <div className="space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="rounded-full bg-blue-100 dark:bg-blue-900 p-1 mt-1">
                      <div className="h-2 w-2 rounded-full bg-blue-600 dark:bg-blue-400" />
                    </div>
                    <div>
                      <p className="font-medium text-sm">Exclusive Previews</p>
                      <p className="text-xs text-muted-foreground">
                        Get sneak peeks as we prepare to launch
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="rounded-full bg-blue-100 dark:bg-blue-900 p-1 mt-1">
                      <div className="h-2 w-2 rounded-full bg-blue-600 dark:bg-blue-400" />
                    </div>
                    <div>
                      <p className="font-medium text-sm">First Access</p>
                      <p className="text-xs text-muted-foreground">
                        Personal invitation before anyone else
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="rounded-full bg-blue-100 dark:bg-blue-900 p-1 mt-1">
                      <div className="h-2 w-2 rounded-full bg-blue-600 dark:bg-blue-400" />
                    </div>
                    <div>
                      <p className="font-medium text-sm">Early Bird Benefits</p>
                      <p className="text-xs text-muted-foreground">
                        Special pricing and bonus features
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Clock className="h-4 w-4" />
                Expected launch: ~15 days from now
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Call to Action */}
        <div className="text-center space-y-3">
          <p className="text-sm text-muted-foreground">
            While you wait, learn more about how probate leads can grow your business
          </p>
          <div className="flex gap-3 justify-center">
            <Button variant="outline" size="sm" asChild>
              <Link to="/how-it-works">
                How It Works
                <ArrowRight className="ml-1 h-4 w-4" />
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link to="/contact">
                Contact Us
              </Link>
            </Button>
          </div>
        </div>

        {/* Footer Note */}
        <div className="rounded-lg border border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950 p-4">
          <p className="text-sm text-green-700 dark:text-green-300 text-center">
            <strong>Pro tip:</strong> Add us to your contacts so our launch email doesn't land in spam!
          </p>
        </div>
      </div>
    </div>
  )
}
