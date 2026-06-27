import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { deploymentLogs } from '../api/compose'

interface LogsDialogProps {
  deploymentId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function LogsDialog({ deploymentId, open, onOpenChange }: LogsDialogProps) {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery({
    queryKey: ['compose', 'logs', deploymentId],
    queryFn: () => deploymentLogs(deploymentId, { tail: 200 }),
    enabled: open,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('compose.logs.title', { name: deploymentId })}</DialogTitle>
        </DialogHeader>
        {isLoading && (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        )}
        {data !== undefined && (
          <pre className="max-h-96 overflow-auto rounded bg-muted p-3 text-xs">
            {data.output || '(empty)'}
          </pre>
        )}
        <div className="flex justify-end pt-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('common.close')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
