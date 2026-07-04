import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Copy, ExternalLink, Link2, MoreVertical, PlayCircle, RefreshCw, TerminalSquare, Trash2,
} from 'lucide-react'
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
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import {
  useDeleteTestHost, useResolveTestHostIp, useTestHostLinks, type TestHost,
} from './useTestVm'
import TestHostLinksDialog from './TestHostLinksDialog'
import type { ComposeDeployment } from '@/features/compose/api/types'
import HostServicesBlock from '@/features/compose/components/HostServicesBlock'

interface Props {
  wsName: string
  host: TestHost
  deployments: ComposeDeployment[]
  onOpenSsh: (host: TestHost) => void
}

/**
 * Bloc d'une machine de test : barre d'en-tête (alias + nom/IP + menu d'actions)
 * et, en dessous, les services docker-compose qui y tournent — un seul bloc
 * visuel qui regroupe la machine et ce qui s'exécute dedans.
 */
export default function TestHostBlock({ wsName, host, deployments, onOpenSsh }: Props) {
  const { t } = useTranslation()
  const del = useDeleteTestHost(wsName)
  const resolve = useResolveTestHostIp(wsName)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [launchOpen, setLaunchOpen] = useState(false)
  const [linksOpen, setLinksOpen] = useState(false)
  const { data: links = [] } = useTestHostLinks(wsName, host.name)

  function handleResolve() {
    toast.promise(resolve.mutateAsync(host.name), {
      loading: t('workspaces.testHosts.resolving'),
      success: (r) => t('workspaces.testHosts.resolved', { ip: r.ip }),
      error: (e) => (e instanceof Error ? e.message : t('workspaces.testHosts.resolveFailed')),
    })
  }

  function confirmDeleteHost() {
    setConfirmDelete(false)
    toast.promise(del.mutateAsync(host.name), {
      loading: t('workspaces.testHosts.deleting'),
      success: t('workspaces.testHosts.deleted'),
      error: (e) => (e instanceof Error ? e.message : t('workspaces.testHosts.deleteFailed')),
    })
  }

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="font-semibold text-sm truncate">{host.alias}</span>
          <span className="font-mono text-xs text-muted-foreground truncate">
            {host.name} · {host.ip}
          </span>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0 shrink-0"
              aria-label={t('workspaces.testHosts.actionsMenu')}
            >
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem onSelect={() => setLaunchOpen(true)} className="gap-2">
              <PlayCircle className="h-3.5 w-3.5" />
              {t('workspaces.testHosts.launchService')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onOpenSsh(host)} className="gap-2">
              <TerminalSquare className="h-3.5 w-3.5" />
              {t('workspaces.testHosts.openSsh')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={handleResolve} className="gap-2">
              <RefreshCw className="h-3.5 w-3.5" />
              {t('workspaces.testHosts.resolveIp')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {links.map((link) => (
              <DropdownMenuItem
                key={link.key}
                className="gap-2"
                onSelect={() => window.open(link.url, '_blank', 'noopener,noreferrer')}
              >
                <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">{link.key}</span>
                {/* stopPropagation : copier ne doit ni ouvrir l'URL ni fermer le menu */}
                <button
                  type="button"
                  className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
                  aria-label={t('workspaces.testHostLinks.copy', { key: link.key })}
                  onClick={(e) => {
                    e.stopPropagation()
                    e.preventDefault()
                    void navigator.clipboard.writeText(link.url).then(
                      () => toast.success(t('workspaces.testHostLinks.copied')),
                      () => toast.error(t('workspaces.testHostLinks.copyFailed')),
                    )
                  }}
                  onPointerDown={(e) => e.stopPropagation()}
                  onPointerUp={(e) => e.stopPropagation()}
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
              </DropdownMenuItem>
            ))}
            <DropdownMenuItem onSelect={() => setLinksOpen(true)} className="gap-2">
              <Link2 className="h-3.5 w-3.5" />
              {t('workspaces.testHostLinks.manage')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="gap-2 text-destructive focus:text-destructive"
              onSelect={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-3.5 w-3.5" />
              {t('workspaces.testHosts.delete')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="p-2">
        <HostServicesBlock
          nodeId={host.name}
          nodeLabel={host.alias}
          namingHint={wsName}
          deployments={deployments}
          launchOpen={launchOpen}
          onLaunchOpenChange={setLaunchOpen}
        />
      </div>

      {linksOpen && (
        <TestHostLinksDialog
          open
          onOpenChange={(o) => { if (!o) setLinksOpen(false) }}
          wsName={wsName}
          hostName={host.name}
          hostAlias={host.alias}
        />
      )}

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.testHosts.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {t('workspaces.testHosts.deleteDescription', { alias: host.alias, name: host.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
              {t('workspaces.testVm.cancel')}
            </Button>
            <Button variant="destructive" size="sm" onClick={confirmDeleteHost}>
              {t('workspaces.testHosts.confirmDelete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
