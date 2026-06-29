import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useWorkspaceMessages } from './useWorkspaceMessages'

interface Props {
  workspaceName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Button size="sm" variant="outline" onClick={handleCopy} className="shrink-0 gap-1.5">
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t('workspaces.messages.copied') : t('workspaces.messages.copy')}
    </Button>
  )
}

export default function WorkspaceMessagesDialog({ workspaceName, open, onOpenChange }: Props) {
  const { t } = useTranslation()
  const { data: messages, isLoading } = useWorkspaceMessages(workspaceName, open)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t('workspaces.messages.title', { name: workspaceName })}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t('workspaces.messages.description', { name: workspaceName })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 max-h-[60vh] overflow-auto pr-1">
          {isLoading && (
            <p className="text-sm text-muted-foreground">{t('workspaces.messages.loading')}</p>
          )}
          {!isLoading && (!messages || messages.length === 0) && (
            <p className="text-sm text-muted-foreground">{t('workspaces.messages.empty')}</p>
          )}
          {messages?.map((msg) => (
            <div key={msg.id ?? msg.type} className="rounded-md border bg-muted/40 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="rounded-sm bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                  {msg.type}
                </span>
                <CopyButton text={msg.message} />
              </div>
              <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">
                {msg.message}
              </pre>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
