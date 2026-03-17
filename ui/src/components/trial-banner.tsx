import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Clock, Zap } from 'lucide-react'

interface TrialStatusResponse {
  trialStatus: {
    userId: string
    journeyType: string
    journeyStep: string
    isTrialing: boolean
    trialExpiresOn: string
    daysRemaining: number
  }
}

async function getTrialStatus(userId: string): Promise<TrialStatusResponse> {
  const token = localStorage.getItem('access_token')
  const response = await fetch(
    `/real-estate/probate-leads/journeys/trial-status/${userId}`,
    {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    }
  )

  if (!response.ok) {
    throw new Error('Failed to fetch trial status')
  }

  return response.json()
}

interface TrialBannerProps {
  onSubscribe?: () => void
}

export function TrialBanner({ onSubscribe }: TrialBannerProps) {
  const { payload } = useAuth()
  const userId = payload?.sub as string | undefined

  const { data: trialData } = useQuery({
    queryKey: ['trialStatus', userId],
    queryFn: () => {
      if (!userId) {
        return Promise.reject('No user ID')
      }
      return getTrialStatus(userId)
    },
    enabled: !!userId,
    refetchInterval: 1000 * 60 * 60, // Refetch every hour
  })

  const trialStatus = trialData?.trialStatus

  // Only show banner for active trials
  if (!trialStatus || !trialStatus.isTrialing || trialStatus.daysRemaining < 0) {
    return null
  }

  const isExpiringSoon = trialStatus.daysRemaining <= 3
  const expiryDate = new Date(trialStatus.trialExpiresOn).toLocaleDateString()

  return (
    <div className={`rounded-lg border p-4 ${
      isExpiringSoon
        ? 'border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950'
        : 'border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950'
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className={`mt-1 ${
            isExpiringSoon ? 'text-amber-600 dark:text-amber-400' : 'text-blue-600 dark:text-blue-400'
          }`}>
            {isExpiringSoon ? <Zap className="h-5 w-5" /> : <Clock className="h-5 w-5" />}
          </div>

          <div className="space-y-1">
            <h3 className={`font-medium ${
              isExpiringSoon ? 'text-amber-900 dark:text-amber-100' : 'text-blue-900 dark:text-blue-100'
            }`}>
              {isExpiringSoon ? '⚡ Trial Expires Soon!' : '🎉 Free Trial Active'}
            </h3>

            <div className={`text-sm ${
              isExpiringSoon ? 'text-amber-700 dark:text-amber-300' : 'text-blue-700 dark:text-blue-300'
            }`}>
              <p>
                <span className="font-semibold">
                  {trialStatus.daysRemaining === 0
                    ? 'Trial expires today'
                    : `${trialStatus.daysRemaining} day${trialStatus.daysRemaining === 1 ? '' : 's'} remaining`}
                </span>
                {trialStatus.daysRemaining > 0 && ` (expires ${expiryDate})`}
              </p>
              <p className="mt-1">
                {isExpiringSoon
                  ? "Don't lose access to fresh probate leads!"
                  : 'Enjoying your trial? Subscribe to continue after it ends.'}
              </p>
            </div>
          </div>
        </div>

        <Button
          onClick={onSubscribe}
          size="sm"
          className={
            isExpiringSoon
              ? 'bg-amber-600 hover:bg-amber-700 dark:bg-amber-500 dark:hover:bg-amber-600'
              : 'bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600'
          }
        >
          {isExpiringSoon ? 'Subscribe Now' : 'Subscribe'}
        </Button>
      </div>
    </div>
  )
}
