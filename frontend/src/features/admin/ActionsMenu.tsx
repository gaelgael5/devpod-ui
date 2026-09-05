// Menu « Actions » d'une ligne, et exécution de l'action choisie.
//
// Deux usages, un seul composant : les actions d'un hyperviseur (page
// Hyperviseurs) et celles d'un nœud (page Hôtes Docker). Ce qui change est la
// route ; le reste — formulaire d'arguments issu du descripteur, confirmation,
// sortie streamée — est identique.

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { apiFetchJson } from '@/shared/api/client'
import HypervisorArgsForm from './HypervisorArgsForm'
import type { ActionDisponible } from './useHypervisorActions'
import {
  flattenArgs, useExecuteScript, valeursParDefaut, type ScriptSpec,
} from './useProxmoxScript'

interface Props {
  /** Base des routes de l'action : `/admin/hypervisors/pve1` ou `/admin/hosts/host-105-1`. */
  base: string
  /** Ce qui est visé, affiché dans la confirmation — un clic ne suffit pas. */
  cibleLabel: string
  actions: ActionDisponible[]
}

export default function ActionsMenu({ base, cibleLabel, actions }: Props) {
  const { t } = useTranslation()
  const [choisie, setChoisie] = useState<ActionDisponible | null>(null)

  // Pas de menu grisé : une ligne sans action déclarée n'a rien à proposer, et
  // un bouton mort se re-teste à chaque passage.
  if (actions.length === 0) return null

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="ghost">
            {t('admin.hypervisorActions.menu')}
            <ChevronDown className="ml-1 h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {actions.map((a) => (
            <DropdownMenuItem key={a.slug} onSelect={() => setChoisie(a)}>
              {a.label || a.slug}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      {choisie && (
        <ActionDialog
          base={base}
          cibleLabel={cibleLabel}
          action={choisie}
          onClose={() => setChoisie(null)}
        />
      )}
    </>
  )
}

function ActionDialog({
  base,
  cibleLabel,
  action,
  onClose,
}: {
  base: string
  cibleLabel: string
  action: ActionDisponible
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [saisies, setSaisies] = useState<Record<string, string>>({})
  const [lance, setLance] = useState(false)
  const { logs, running, done, error, executeAt, reset } = useExecuteScript()

  const spec = useQuery<ScriptSpec>({
    queryKey: ['admin', 'action-script', base, action.slug],
    queryFn: () => apiFetchJson<ScriptSpec>(`${base}/actions/${action.slug}/script`),
    retry: false,
  })

  // Les défauts ne sont connus qu'une fois le descripteur récupéré : on les
  // DÉRIVE au rendu plutôt que de les recopier dans l'état par un effet, qui
  // écraserait au passage une saisie faite entre-temps.
  const args = useMemo(() => spec.data?.args ?? [], [spec.data])
  const values = useMemo(
    () => ({ ...valeursParDefaut(args), ...saisies }),
    [args, saisies],
  )
  const manquants = flattenArgs(args).filter((a) => a.required && !values[a.arg])

  function lancer() {
    setLance(true)
    reset()
    void executeAt(`${base}/actions/${action.slug}/execute`, values)
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !running && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {action.label || action.slug} — {cibleLabel}
          </DialogTitle>
        </DialogHeader>

        {!lance && (
          <div className="flex flex-col gap-3">
            {/* Redimensionner un disque ou de la RAM depuis une ligne de tableau
                dense mérite un temps d'arrêt : on nomme l'action ET sa cible. */}
            <p className="text-sm text-muted-foreground">
              {t('admin.hypervisorActions.confirm', {
                action: action.label || action.slug,
                cible: cibleLabel,
              })}
            </p>
            {spec.isLoading && <p className="text-muted-foreground">…</p>}
            {spec.isError && (
              <p className="text-sm text-destructive">
                {spec.error instanceof Error ? spec.error.message : t('errors.loadFailed')}
              </p>
            )}
            {spec.data && args.length > 0 && (
              <HypervisorArgsForm
                args={args}
                values={values}
                onChange={(arg, v) => setSaisies((s) => ({ ...s, [arg]: v }))}
              />
            )}
          </div>
        )}

        {lance && (
          <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 font-mono text-xs whitespace-pre-wrap">
            {logs}
            {error && <span className="text-destructive">{error}</span>}
          </pre>
        )}

        <DialogFooter>
          {!lance ? (
            <>
              <Button variant="outline" onClick={onClose}>
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button onClick={lancer} disabled={spec.isLoading || manquants.length > 0}>
                {t('admin.hypervisorActions.run')}
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={onClose} disabled={running}>
              {running && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
              {done ? t('common.close') : t('admin.hypervisorActions.running')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
