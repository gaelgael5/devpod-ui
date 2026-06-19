import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { PinInput } from './components/PinInput'
import { usePinUnlock } from './api'

export default function VaultUnlock() {
  const navigate = useNavigate()
  const { mutateAsync, isPending } = usePinUnlock()
  const [error, setError] = useState<string | null>(null)

  const handlePin = async (pin: string) => {
    setError(null)
    try {
      await mutateAsync(pin)
      navigate('/')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : ''
      setError(
        msg.includes('423')
          ? 'Compte verrouillé — réessayez dans quelques minutes.'
          : 'PIN incorrect.'
      )
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Déverrouiller le coffre</CardTitle>
          <CardDescription>Saisissez votre PIN pour accéder à l&apos;application.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <PinInput onComplete={handlePin} disabled={isPending} showSubmit maskDelay={0} />
          <p className="text-muted-foreground text-center text-sm">
            <Link to="/vault/recover" className="underline">
              Code de secours oublié ?
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
