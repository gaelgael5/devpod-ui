import { useTranslation } from 'react-i18next'
import { useAgentMessageDetail } from './useAgentMessages'

/** Corps complet d'un message + fil des réponses liées (reply_to). */
export default function AgentMessageDetail({ id }: { id: string }) {
  const { t } = useTranslation()
  const { data, isLoading } = useAgentMessageDetail(id)

  if (isLoading || !data) {
    return <p className="text-xs text-muted-foreground">{t('common.loading')}</p>
  }

  return (
    <div className="flex flex-col gap-2">
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
        {data.body}
      </pre>
      {data.replies.length > 0 && (
        <div className="text-xs text-muted-foreground">
          <span className="font-medium">{t('agentMessages.thread')}</span>
          <ul className="mt-1 flex flex-col gap-0.5">
            {data.replies.map((r) => (
              <li key={r.message_id} className="font-mono">
                {r.message_id.slice(0, 8)} — {r.status}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
