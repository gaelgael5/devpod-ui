import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { PinInput } from './components/PinInput'
import { RecoveryCodeDisplay } from './components/RecoveryCodeDisplay'
import { usePinSetup } from './api'

export default function VaultSetup() {
  const navigate = useNavigate()
  const { mutateAsync, isPending } = usePinSetup()
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handlePin = async (pin: string) => {
    setError(null)
    try {
      const result = await mutateAsync(pin)
      setRecoveryCode(result.recovery_code)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : ''
      if (msg.includes('409')) {
        // PIN déjà configuré — rediriger vers unlock
        navigate('/vault/unlock', { replace: true })
      } else {
        setError(`Erreur lors de la configuration du PIN : ${msg}`)
      }
    }
  }

  if (recoveryCode) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Code de secours</CardTitle>
          </CardHeader>
          <CardContent>
            <RecoveryCodeDisplay
              code={recoveryCode}
              onConfirmed={() => navigate('/')}
            />
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Créer votre PIN</CardTitle>
          <CardDescription>6 chiffres pour protéger vos clés Harpocrate.</CardDescription>
        </CardHeader>
        <CardContent className="pt-2 space-y-3">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <PinInput onComplete={handlePin} disabled={isPending} showSubmit />
        </CardContent>
      </Card>
    </div>
  )
}
