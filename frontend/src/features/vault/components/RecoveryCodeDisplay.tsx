import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'

interface RecoveryCodeDisplayProps {
  code: string
  onConfirmed: () => void
}

export function RecoveryCodeDisplay({ code, onConfirmed }: RecoveryCodeDisplayProps) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-4">
      <Alert variant="destructive">
        <AlertDescription>
          Notez ce code maintenant — il ne sera plus affiché. Sans lui, un PIN oublié est
          irrécupérable.
        </AlertDescription>
      </Alert>
      <div className="bg-muted flex items-center gap-2 rounded-lg p-4">
        <span className="flex-1 text-center font-mono text-lg tracking-widest">{code}</span>
        <Button variant="ghost" size="sm" onClick={copy}>
          {copied ? 'Copié ✓' : 'Copier'}
        </Button>
      </div>
      <Button className="w-full" onClick={onConfirmed}>
        J&apos;ai noté mon code de secours
      </Button>
    </div>
  )
}
