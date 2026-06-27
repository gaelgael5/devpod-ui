import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PinInput } from './components/PinInput'
import { RecoveryCodeDisplay } from './components/RecoveryCodeDisplay'
import { usePinRecover } from './api'

export default function VaultRecover() {
  const navigate = useNavigate()
  const { mutateAsync, isPending } = usePinRecover()
  const [recoveryInput, setRecoveryInput] = useState('')
  const [newPin, setNewPin] = useState('')
  const [newCode, setNewCode] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    setError(null)
    if (newPin.length !== 6) return
    try {
      const result = await mutateAsync({ recovery_code: recoveryInput, new_pin: newPin })
      setNewCode(result.recovery_code)
    } catch {
      setError('Code de secours incorrect.')
    }
  }

  if (newCode) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Nouveau code de secours</CardTitle>
          </CardHeader>
          <CardContent>
            <RecoveryCodeDisplay code={newCode} onConfirmed={() => navigate('/')} />
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Récupération par code de secours</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-2">
            <Label>Code de secours</Label>
            <Input
              value={recoveryInput}
              onChange={(e) => setRecoveryInput(e.target.value)}
              placeholder="xxxx-xxxx-xxxx-xxxx-xxxx-xxxx"
              className="font-mono"
            />
          </div>
          <div className="space-y-2">
            <Label>Nouveau PIN</Label>
            <div className="flex justify-center">
              <PinInput onComplete={setNewPin} disabled={isPending} />
            </div>
          </div>
          <Button
            className="w-full"
            onClick={handleSubmit}
            disabled={isPending || newPin.length !== 6 || !recoveryInput}
          >
            Réinitialiser le PIN
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
