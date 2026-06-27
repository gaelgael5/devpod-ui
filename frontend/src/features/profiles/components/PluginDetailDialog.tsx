import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { usePluginReadme } from '../hooks/usePluginReadme'
import type { PluginSummary } from '../api/types'

interface Props {
  plugin: PluginSummary | null
  selected: boolean
  onToggle: () => void
  onClose: () => void
}

export function PluginDetailDialog({ plugin, selected, onToggle, onClose }: Props) {
  const { t } = useTranslation()
  const { data: readme, isLoading, isError: readmeError } = usePluginReadme(plugin?.namespace, plugin?.name)

  return (
    <Dialog open={Boolean(plugin)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[80vh] max-w-3xl overflow-y-auto">
        {plugin && (
          <>
            <DialogHeader>
              <DialogTitle>{plugin.display_name}</DialogTitle>
              <DialogDescription className="sr-only">
                {plugin.namespace} · v{plugin.version}
              </DialogDescription>
            </DialogHeader>
            <p className="text-sm text-muted-foreground">
              {plugin.namespace} · v{plugin.version}
            </p>
            <Button
              size="sm"
              variant={selected ? 'secondary' : 'default'}
              onClick={onToggle}
            >
              {t(selected ? 'profiles.plugins.remove' : 'profiles.plugins.add')}
            </Button>
            <div className="prose prose-sm dark:prose-invert mt-4 max-w-none">
              {isLoading ? (
                <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
              ) : readmeError ? (
                <p className="text-sm text-muted-foreground">{t('profiles.plugins.errors.readme')}</p>
              ) : readme ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{readme}</ReactMarkdown>
              ) : null}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
