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
import { useWorkspaceSshKey } from './useWorkspaceSshKey'

interface Props {
  workspaceName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function SshKeyDialog({ workspaceName, open, onOpenChange }: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const { data, isLoading, isError } = useWorkspaceSshKey(workspaceName, open)

  async function handleCopy() {
    if (!data) return
    await navigator.clipboard.writeText(data.public_key)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('workspaces.sshKey.title')}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t('workspaces.sshKey.hint')}</p>
        {isLoading && <p className="text-sm text-muted-foreground">…</p>}
        {isError && (
          <p className="text-sm text-destructive">{t('workspaces.sshKey.notGenerated')}</p>
        )}
        {data && (
          <div className="flex flex-col gap-2">
            <textarea
              readOnly
              value={data.public_key}
              rows={4}
              className="w-full rounded-md border bg-muted px-3 py-2 font-mono text-xs resize-none"
            />
            <Button size="sm" variant="outline" className="self-start" onClick={handleCopy}>
              {copied
                ? <><Check className="h-4 w-4 mr-1" />{t('workspaces.sshKey.copied')}</>
                : <><Copy className="h-4 w-4 mr-1" />{t('workspaces.sshKey.copy')}</>
              }
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
