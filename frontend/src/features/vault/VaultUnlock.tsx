import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { PinInput } from './components/PinInput'
import { usePinUnlock, useVaultReset } from './api'

export default function VaultUnlock() {
  const navigate = useNavigate()
  const { mutateAsync, isPending } = usePinUnlock()
  const { mutateAsync: resetVault, isPending: isResetting } = useVaultReset()
  const [error, setError] = useState<string | null>(null)
  const [showResetDialog, setShowResetDialog] = useState(false)

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
          : 'PIN incorrect.',
      )
    }
  }

  const handleReset = async () => {
    await resetVault()
    setShowResetDialog(false)
    navigate('/vault/setup', { replace: true })
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
          <div className="text-muted-foreground flex justify-between text-center text-sm">
            <Link to="/vault/recover" className="underline">
              Code de secours oublié ?
            </Link>
            <button
              type="button"
              onClick={() => setShowResetDialog(true)}
              className="text-destructive underline"
            >
              Réinitialiser le coffre
            </button>
          </div>
        </CardContent>
      </Card>

      <Dialog open={showResetDialog} onOpenChange={setShowResetDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Réinitialiser le coffre ?</DialogTitle>
            <DialogDescription>
              Cette action supprime définitivement votre PIN et toutes les clés de coffre
              enregistrées. Vous devrez reconfigurer un nouveau PIN et re-saisir vos clés.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowResetDialog(false)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleReset} disabled={isResetting}>
              {isResetting ? 'Réinitialisation…' : 'Réinitialiser'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
