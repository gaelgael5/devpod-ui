import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  useOrphanDeployments, usePurgeOrphanDeployments,
} from '@/features/compose/hooks/useCompose'

interface Props {
  open: boolean
  onClose: () => void
}

/**
 * Purge des déploiements dont le nœud a disparu de l'inventaire.
 *
 * La liste s'affiche AVANT toute suppression : c'est une opération destructive
 * sur des données, et rien ne distingue à l'œil nu une ligne fantôme d'un
 * service qui tourne — c'est justement le problème qu'elle corrige.
 */
export default function OrphanDeploymentsDialog({ open, onClose }: Props) {
  const { t } = useTranslation()
  const { data: orphelins = [], isLoading, isError } = useOrphanDeployments(open)
  const purger = usePurgeOrphanDeployments()

  function confirmer() {
    purger.mutate(undefined, {
      onSuccess: (r) => {
        toast.success(t('admin.orphans.purged', { count: r.purged }))
        onClose()
      },
      onError: () => toast.error(t('admin.orphans.purgeFailed')),
    })
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && !purger.isPending) onClose() }}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('admin.orphans.title')}</DialogTitle>
        </DialogHeader>

        <p className="text-sm text-muted-foreground">{t('admin.orphans.hint')}</p>

        {isLoading && (
          <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('admin.orphans.loading')}
          </div>
        )}
        {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}

        {!isLoading && !isError && orphelins.length === 0 && (
          <p className="rounded-md border border-dashed bg-muted/40 p-3 text-sm text-muted-foreground">
            {t('admin.orphans.empty')}
          </p>
        )}

        {orphelins.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-1 pr-3 font-medium">{t('admin.orphans.colNode')}</th>
                <th className="py-1 pr-3 font-medium">{t('admin.orphans.colName')}</th>
                <th className="py-1 pr-3 font-medium">{t('admin.orphans.colTemplate')}</th>
                <th className="py-1 font-medium">{t('admin.orphans.colOwner')}</th>
              </tr>
            </thead>
            <tbody>
              {orphelins.map((d) => (
                <tr key={d.uid} className="border-b last:border-0">
                  <td className="py-1 pr-3 font-mono text-xs">{d.node_id}</td>
                  <td className="py-1 pr-3">{d.id}</td>
                  <td className="py-1 pr-3 text-muted-foreground">{d.template_id}</td>
                  <td className="py-1 text-muted-foreground">{d.owner_login}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={purger.isPending}>
            {t('admin.orphans.cancel')}
          </Button>
          <Button
            variant="destructive"
            onClick={confirmer}
            disabled={orphelins.length === 0 || purger.isPending}
          >
            {purger.isPending
              ? '…'
              : t('admin.orphans.confirm', { count: orphelins.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
