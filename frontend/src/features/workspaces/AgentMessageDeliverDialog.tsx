import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useWorkspaceSessions } from './useWorkspaceSessions'
import { useDeliverAgentMessage, type AgentMessage } from './useAgentMessages'

interface Props {
  message: AgentMessage
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Choix de la session cible du workspace destinataire + transmission (spec 34 §6). */
export default function AgentMessageDeliverDialog({ message, open, onOpenChange }: Props) {
  const { t } = useTranslation()
  const { data: sessions = [] } = useWorkspaceSessions(open ? message.to_name : undefined)
  const deliver = useDeliverAgentMessage()
  const [picked, setPicked] = useState<string>('')
  // Session effective dérivée au rendu (pas d'effet) : choix explicite s'il tient
  // encore dans la liste, sinon pré-sélection quand il n'y a qu'une session.
  const session =
    picked && sessions.includes(picked)
      ? picked
      : sessions.length === 1
        ? sessions[0]
        : ''

  function transmit() {
    if (!session) return
    deliver.mutate(
      { id: message.id, session },
      {
        onSuccess: () => {
          toast.success(t('agentMessages.deliver.done'))
          onOpenChange(false)
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : t('agentMessages.deliver.failed')),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('agentMessages.deliver.title', { ws: message.to_name })}</DialogTitle>
          <DialogDescription>{t('agentMessages.deliver.description')}</DialogDescription>
        </DialogHeader>

        {sessions.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('agentMessages.deliver.noSession')}</p>
        ) : (
          <Select value={session} onValueChange={setPicked}>
            <SelectTrigger>
              <SelectValue placeholder={t('agentMessages.deliver.pickSession')} />
            </SelectTrigger>
            <SelectContent>
              {sessions.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('agentMessages.cancel')}
          </Button>
          <Button onClick={transmit} disabled={!session || deliver.isPending}>
            {t('agentMessages.deliver.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
