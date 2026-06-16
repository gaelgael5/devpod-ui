import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

interface Props {
  open: boolean
  publicKey: string
  onClose: () => void
}

export default function GitCredentialPublicKeyDialog({ open, publicKey, onClose }: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    void navigator.clipboard.writeText(publicKey)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog open={open} onOpenChange={open => { if (!open) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('gitCredentials.publicKeyDialogTitle')}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t('gitCredentials.publicKeyHint')}</p>
        <Textarea
          readOnly
          value={publicKey}
          className="font-mono text-xs"
          rows={4}
        />
        <div className="flex justify-end">
          <Button type="button" size="sm" onClick={handleCopy}>
            {copied ? (
              <>
                <Check className="mr-1.5 h-4 w-4" />
                {t('gitCredentials.publicKeyCopied')}
              </>
            ) : (
              <>
                <Copy className="mr-1.5 h-4 w-4" />
                {t('gitCredentials.publicKeyCopy')}
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
