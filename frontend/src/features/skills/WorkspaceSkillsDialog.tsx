import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import SkillShLink from './SkillShLink'
import {
  useMyGrants,
  usePlaceSkill,
  useRemovePlacement,
  useWorkspaceSkills,
} from './api'

const PLACEMENT_CLASS: Record<string, string> = {
  verified: 'bg-green-500/10 text-green-700 dark:text-green-400',
  unverified: 'bg-red-500/10 text-red-700 dark:text-red-400',
  placed: 'bg-muted text-muted-foreground',
  requested: 'bg-muted text-muted-foreground',
}

/**
 * Gestion des skills d'un workspace : placements existants (statut de
 * vérification) + installation d'une skill VALIDÉE (grant granted uniquement —
 * le backend refuse tout le reste). L'installation tire le HEAD : une dérive
 * → unverified, pas de routage, re-validation dans l'onglet Skills.
 */
export default function WorkspaceSkillsDialog({
  wsName,
  onClose,
}: {
  wsName: string
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { data: placements = [], isLoading } = useWorkspaceSkills(wsName, true)
  const { data: grants = [] } = useMyGrants()
  const place = usePlaceSkill(wsName)
  const remove = useRemovePlacement(wsName)
  const [selected, setSelected] = useState('')

  const placeable = useMemo(() => {
    const placed = new Set(placements.map((p) => p.skill_id))
    return grants.filter((g) => g.statut === 'granted' && !placed.has(g.skill_id))
  }, [grants, placements])

  function install() {
    if (!selected) return
    place.mutate(selected, {
      onSuccess: (p) => {
        toast.success(
          p.placement_statut === 'unverified' || p.installed_hash !== p.approved_hash
            ? t('skills.ws.installedUnverified')
            : t('skills.ws.installed'),
        )
        setSelected('')
      },
      onError: (e: Error) => toast.error(e.message),
    })
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('skills.ws.title', { name: wsName })}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">…</p>
          ) : placements.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('skills.ws.empty')}</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {placements.map((p) => (
                <li
                  key={p.placement_id}
                  className="flex items-center gap-2 rounded-md border bg-background px-3 py-2"
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-sm">
                    {p.skill_id}
                  </span>
                  <SkillShLink skillId={p.skill_id} />
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${PLACEMENT_CLASS[p.placement_statut] ?? 'bg-muted text-muted-foreground'}`}
                  >
                    {t(`skills.ws.placement.${p.placement_statut}`)}
                  </span>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6 text-muted-foreground hover:text-destructive"
                    disabled={remove.isPending}
                    aria-label={t('skills.ws.remove', { name: p.skill_id })}
                    onClick={() =>
                      remove.mutate(p.placement_id, {
                        onSuccess: () => toast.success(t('skills.ws.removed')),
                        onError: (e: Error) => toast.error(e.message),
                      })
                    }
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-end gap-2 border-t pt-3">
            <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs">
              {t('skills.ws.installLabel')}
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                className="h-9 w-full rounded-md border bg-background px-2 text-sm"
              >
                <option value="">
                  {placeable.length === 0
                    ? t('skills.ws.noGranted')
                    : t('skills.ws.selectPlaceholder')}
                </option>
                {placeable.map((g) => (
                  <option key={g.id} value={g.skill_id}>
                    {g.skill_id}
                  </option>
                ))}
              </select>
            </label>
            <Button size="sm" disabled={!selected || place.isPending} onClick={install}>
              {place.isPending ? t('skills.ws.installing') : t('skills.ws.install')}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t('skills.ws.hint')}</p>
        </div>
      </DialogContent>
    </Dialog>
  )
}
