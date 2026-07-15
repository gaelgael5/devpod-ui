import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Boxes } from 'lucide-react'
import { useHostStacks } from './useTestVm'

interface Props {
  wsName: string
  hostName: string
  enabled: boolean
  /** Noms de stacks déjà affichées comme services gérés par le portail (dédup). */
  excludeNames: string[]
}

/** Teinte du badge selon l'état renvoyé par `docker compose ls` (ex. "running(2)"). */
function statusClass(status: string): string {
  const s = status.toLowerCase()
  if (s.includes('running')) return 'bg-green-500/10 text-green-700 dark:text-green-400'
  if (s.includes('exited') || s.includes('stopped') || s.includes('dead'))
    return 'bg-muted text-muted-foreground'
  return 'bg-orange-500/10 text-orange-700 dark:text-orange-400'
}

/**
 * Sous-blocs des stacks docker RÉELLEMENT en cours sur la machine (vue live via
 * son docker, `docker compose ls`), au-delà des services déployés par le portail.
 * Purement informatif (lecture seule).
 */
export default function TestHostStacks({ wsName, hostName, enabled, excludeNames }: Props) {
  const { t } = useTranslation()
  const { data: stacks = [] } = useHostStacks(wsName, hostName, enabled)

  const excluded = useMemo(() => new Set(excludeNames), [excludeNames])
  const extra = useMemo(
    () => stacks.filter((s) => !excluded.has(s.name)),
    [stacks, excluded],
  )

  if (extra.length === 0) return null

  return (
    <div className="mt-2 flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase text-muted-foreground">
        <Boxes className="h-3.5 w-3.5" />
        {t('workspaces.testHostStacks.title')}
      </div>
      {extra.map((s) => (
        <div
          key={s.name}
          className="flex items-center gap-2 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-sm"
        >
          <span className="min-w-0 flex-1 truncate font-mono text-xs font-medium">{s.name}</span>
          {s.status && (
            <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${statusClass(s.status)}`}>
              {s.status}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
