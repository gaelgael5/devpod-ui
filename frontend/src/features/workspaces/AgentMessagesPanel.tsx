import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, ChevronDown, ChevronRight, Send, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import AgentMessageDetail from './AgentMessageDetail'
import AgentMessageDeliverDialog from './AgentMessageDeliverDialog'
import {
  useCancelAgentMessage, usePendingAgentMessages, type AgentMessage,
} from './useAgentMessages'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Panneau « Demandes inter-agents » : file des messages pending pilotée par l'utilisateur. */
export default function AgentMessagesPanel({ open, onOpenChange }: Props) {
  const { t } = useTranslation()
  const { data: messages = [], isLoading } = usePendingAgentMessages()
  const cancel = useCancelAgentMessage()
  const [expanded, setExpanded] = useState<string | null>(null)
  const [deliverFor, setDeliverFor] = useState<AgentMessage | null>(null)

  function reject(id: string) {
    cancel.mutate(id, {
      onSuccess: () => toast.success(t('agentMessages.rejected')),
      onError: (e) => toast.error(e instanceof Error ? e.message : t('agentMessages.rejectFailed')),
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('agentMessages.title')}</DialogTitle>
          <DialogDescription>{t('agentMessages.description')}</DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('agentMessages.empty')}</p>
        ) : (
          <ul className="flex max-h-[60vh] flex-col gap-2 overflow-auto">
            {messages.map((m) => (
              <li key={m.id} className="rounded-md border">
                <div className="flex items-center gap-2 px-3 py-2">
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    onClick={() => setExpanded((e) => (e === m.id ? null : m.id))}
                  >
                    {expanded === m.id
                      ? <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                      : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                    <span className="flex items-center gap-1 shrink-0 font-mono text-xs text-muted-foreground">
                      {m.from_name} <ArrowRight className="h-3 w-3" /> {m.to_name}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">{m.subject}</span>
                  </button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1"
                    onClick={() => setDeliverFor(m)}
                  >
                    <Send className="h-3.5 w-3.5" />
                    {t('agentMessages.transmit')}
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 text-destructive hover:text-destructive"
                    aria-label={t('agentMessages.reject')}
                    disabled={cancel.isPending}
                    onClick={() => reject(m.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
                {expanded === m.id && (
                  <div className="border-t px-3 py-2">
                    <AgentMessageDetail id={m.id} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}

        {deliverFor && (
          <AgentMessageDeliverDialog
            message={deliverFor}
            open
            onOpenChange={(o) => { if (!o) setDeliverFor(null) }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
