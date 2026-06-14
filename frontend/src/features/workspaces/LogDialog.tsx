import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useWorkspaceLogs } from './useWorkspaceLogs'

interface Props {
  workspaceName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function LogDialog({ workspaceName, open, onOpenChange }: Props) {
  const { t } = useTranslation()
  const { data: logs, isLoading } = useWorkspaceLogs(workspaceName, open)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (logs) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {t('workspaces.logs.title', { name: workspaceName })}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t('workspaces.logs.description', { name: workspaceName })}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto rounded-md bg-zinc-950 p-3">
          {isLoading && !logs && (
            <p className="text-xs text-zinc-400">
              {t('workspaces.logs.loading')}
            </p>
          )}
          {!isLoading && !logs && (
            <p className="text-xs text-zinc-400">
              {t('workspaces.logs.empty')}
            </p>
          )}
          {logs && (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-zinc-200">
              {logs}
            </pre>
          )}
          <div ref={bottomRef} />
        </div>
      </DialogContent>
    </Dialog>
  )
}
