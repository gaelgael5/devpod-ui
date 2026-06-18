import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { PinInput } from './components/PinInput'
import { RecoveryCodeDisplay } from './components/RecoveryCodeDisplay'
import { usePinSetup } from './api'

export default function VaultSetup() {
  const navigate = useNavigate()
  const { mutateAsync, isPending } = usePinSetup()
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null)

  const handlePin = async (pin: string) => {
    const result = await mutateAsync(pin)
    setRecoveryCode(result.recovery_code)
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
        <CardContent className="flex justify-center pt-2">
          <PinInput onComplete={handlePin} disabled={isPending} />
        </CardContent>
      </Card>
    </div>
  )
}
