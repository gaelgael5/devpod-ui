import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PlayCircle, TerminalSquare } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useTestHosts, useDeleteTestHost, useResolveTestHostIp, type TestHost } from './useTestVm'
import ServiceLaunchDialog from '@/features/compose/components/ServiceLaunchDialog'

interface Props {
  /** Nom du workspace. */
  wsName: string
  /** Le workspace est démarré (le rebond passe par son container). */
  enabled: boolean
  /** Ouvre un terminal SSH vers la machine de test choisie. */
  onOpenSsh: (host: TestHost) => void
}

/**
 * Menu des machines de test du workspace : ouvre une session SSH (rebond container)
 * ou supprime (détruit la VM). Masqué tant qu'aucune machine n'est attachée.
 */
export default function TestHostsMenu({ wsName, enabled, onOpenSsh }: Props) {
  const { t } = useTranslation()
  const { data: hosts = [] } = useTestHosts(wsName, enabled)
  const del = useDeleteTestHost(wsName)
  const resolve = useResolveTestHostIp(wsName)
  const [toDelete, setToDelete] = useState<TestHost | null>(null)
  const [launchHost, setLaunchHost] = useState<TestHost | null>(null)

  if (hosts.length === 0) return null

  function handleResolve(host: TestHost) {
    toast.promise(resolve.mutateAsync(host.name), {
      loading: t('workspaces.testHosts.resolving'),
      success: (r) => t('workspaces.testHosts.resolved', { ip: r.ip }),
      error: (e) => (e instanceof Error ? e.message : t('workspaces.testHosts.resolveFailed')),
    })
  }

  function confirmDelete() {
    if (!toDelete) return
    const host = toDelete
    setToDelete(null)
    toast.promise(del.mutateAsync(host.name), {
      loading: t('workspaces.testHosts.deleting'),
      success: t('workspaces.testHosts.deleted'),
      error: (e) => (e instanceof Error ? e.message : t('workspaces.testHosts.deleteFailed')),
    })
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline" className="gap-1.5">
            <TerminalSquare className="h-3.5 w-3.5" />
            {t('workspaces.testHosts.menu')}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          {hosts.map((h, idx) => (
            <div key={h.name}>
              {idx > 0 && <DropdownMenuSeparator />}
              <DropdownMenuLabel className="flex flex-col gap-0.5 leading-tight">
                <span className="font-semibold text-sm">{h.name}</span>
                <span className="font-normal font-mono text-xs text-muted-foreground">
                  {h.alias} — {h.ip}
                </span>
              </DropdownMenuLabel>
              <DropdownMenuItem onSelect={() => onOpenSsh(h)}>
                {t('workspaces.testHosts.openSsh')}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => handleResolve(h)}>
                {t('workspaces.testHosts.resolveIp')}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setLaunchHost(h)} className="gap-1.5">
                <PlayCircle className="h-3.5 w-3.5" />
                {t('workspaces.testHosts.launchService')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => setToDelete(h)}
              >
                {t('workspaces.testHosts.delete')}
              </DropdownMenuItem>
            </div>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {launchHost && (
        <ServiceLaunchDialog
          open
          onOpenChange={(o) => { if (!o) setLaunchHost(null) }}
          nodeId={launchHost.name}
          nodeLabel={launchHost.alias}
        />
      )}

      <Dialog open={!!toDelete} onOpenChange={(o) => { if (!o) setToDelete(null) }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.testHosts.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {toDelete && t('workspaces.testHosts.deleteDescription', {
                alias: toDelete.alias, name: toDelete.name,
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="ghost" size="sm" onClick={() => setToDelete(null)}>
              {t('workspaces.testVm.cancel')}
            </Button>
            <Button variant="destructive" size="sm" onClick={confirmDelete}>
              {t('workspaces.testHosts.confirmDelete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
