import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Boxes, Container } from 'lucide-react'
import { useHostDocker } from './useTestVm'

interface Props {
  wsName: string
  hostName: string
  enabled: boolean
  /** Noms de stacks déjà affichées comme services gérés par le portail (dédup). */
  excludeNames: string[]
}

/** Teinte du badge selon l'état docker (ex. "running(2)", "Up 3h", "exited"). */
function statusClass(status: string): string {
  const s = status.toLowerCase()
  if (s.includes('running') || s.startsWith('up'))
    return 'bg-green-500/10 text-green-700 dark:text-green-400'
  if (s.includes('exited') || s.includes('stopped') || s.includes('dead'))
    return 'bg-muted text-muted-foreground'
  return 'bg-orange-500/10 text-orange-700 dark:text-orange-400'
}

function SubBlock({ name, status }: { name: string; status: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-dashed bg-muted/20 px-3 py-2 text-sm">
      <span className="min-w-0 flex-1 truncate font-mono text-xs font-medium">{name}</span>
      {status && (
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${statusClass(status)}`}>
          {status}
        </span>
      )}
    </div>
  )
}

/**
 * Sous-blocs de l'état docker RÉEL de la machine (vue live via son docker) :
 * les stacks compose (`docker compose ls`) hors services gérés par le portail,
 * et les conteneurs hors compose (`docker ps`). Purement informatif.
 */
export default function TestHostStacks({ wsName, hostName, enabled, excludeNames }: Props) {
  const { t } = useTranslation()
  const { data } = useHostDocker(wsName, hostName, enabled)

  const excluded = useMemo(() => new Set(excludeNames), [excludeNames])
  const stacks = useMemo(
    () => (data?.stacks ?? []).filter((s) => !excluded.has(s.name)),
    [data, excluded],
  )
  const containers = data?.containers ?? []

  if (stacks.length === 0 && containers.length === 0) return null

  return (
    <div className="mt-2 flex flex-col gap-2">
      {stacks.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase text-muted-foreground">
            <Boxes className="h-3.5 w-3.5" />
            {t('workspaces.testHostStacks.stacksTitle')}
          </div>
          {stacks.map((s) => (
            <SubBlock key={s.name} name={s.name} status={s.status} />
          ))}
        </div>
      )}
      {containers.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase text-muted-foreground">
            <Container className="h-3.5 w-3.5" />
            {t('workspaces.testHostStacks.containersTitle')}
          </div>
          {containers.map((c) => (
            <SubBlock key={c.name} name={c.name} status={c.status} />
          ))}
        </div>
      )}
    </div>
  )
}
