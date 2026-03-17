import { useNavigate, useSearchParams } from 'react-router-dom'
import { WaitlistForm } from '@/components/waitlist-form'

export default function WaitlistSignup() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const source = searchParams.get('source') // Track where users came from

  const handleSuccess = (email: string) => {
    // Could navigate to a success page or show celebration
    console.log('User joined waitlist:', email)

    // Optional: Track the conversion
    if (source) {
      console.log('Waitlist signup from source:', source)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        <WaitlistForm onSuccess={handleSuccess} />
      </div>
    </div>
  )
}
