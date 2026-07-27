import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueries } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useWorkspaces } from './useWorkspaces'
import { workspaceStatusQueryOptions } from './useWorkspaceStatus'
import { useTestHostShares, useSetTestHostShares } from './useTestVm'

interface Props {
  wsName: string
  hostName: string
  hostAlias: string
  onClose: () => void
}

/**
 * Partage d'une VM de test : liste les autres workspaces RUNNING de l'utilisateur
 * avec une case reflétant l'état de partage courant. Enregistrer réconcilie
 * l'ensemble (les ajouts injectent l'accès SSH + message agent ; les retraits
 * nettoient). Le workspace propriétaire est exclu de la liste.
 */
export default function TestHostShareDialog({ wsName, hostName, hostAlias, onClose }: Props) {
  const { t } = useTranslation()
  const { data: workspaces = [] } = useWorkspaces()
  const { data: currentShared = [], isLoading } = useTestHostShares(wsName, hostName, true)
  const setShares = useSetTestHostShares(wsName, hostName)

  // Statut de chaque workspace (hors propriétaire) pour ne proposer que les running.
  const others = useMemo(
    () => workspaces.filter((w) => w.name !== wsName),
    [workspaces, wsName],
  )
  const statusQueries = useQueries({
    queries: others.map((w) => workspaceStatusQueryOptions(w.name)),
  })
  const runningNames = useMemo(
    () =>
      others
        .filter((_, i) => statusQueries[i]?.data?.status === 'running')
        .map((w) => w.name),
    [others, statusQueries],
  )

  // Sélection = état courant + tout partage déjà actif même si non running (pour
  // pouvoir le décocher). Initialisée quand les données arrivent.
  const [selected, setSelected] = useState<Set<string> | null>(null)
  const effective = selected ?? new Set(currentShared)

  const candidates = useMemo(() => {
    const set = new Set([...runningNames, ...currentShared])
    return [...set].sort()
  }, [runningNames, currentShared])

  function toggle(name: string) {
    const next = new Set(effective)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    setSelected(next)
  }

  function save() {
    toast.promise(setShares.mutateAsync([...effective]), {
      loading: t('workspaces.testHostShare.saving'),
      success: () => { onClose(); return t('workspaces.testHostShare.saved') },
      error: (e) => (e instanceof Error ? e.message : t('workspaces.testHostShare.saveFailed')),
    })
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('workspaces.testHostShare.title', { alias: hostAlias })}</DialogTitle>
          <DialogDescription>{t('workspaces.testHostShare.description')}</DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t('workspaces.testHostShare.loading')}</p>
        ) : candidates.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('workspaces.testHostShare.empty')}</p>
        ) : (
          <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto">
            {candidates.map((name) => (
              <li key={name}>
                <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={effective.has(name)}
                    onChange={() => toggle(name)}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
                  {!runningNames.includes(name) && (
                    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                      {t('workspaces.testHostShare.notRunning')}
                    </span>
                  )}
                </label>
              </li>
            ))}
          </ul>
        )}

        <DialogFooter className="flex-col gap-2 sm:flex-row">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('workspaces.testVm.cancel')}
          </Button>
          <Button size="sm" onClick={save} disabled={setShares.isPending || isLoading}>
            {t('workspaces.testHostShare.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
