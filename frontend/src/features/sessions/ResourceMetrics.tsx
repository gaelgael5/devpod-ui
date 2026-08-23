import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { formatBytes } from './formatBytes'
import type { CpuUsage, DiskUsage, MemoryUsage } from './useSessions'

/** Une mesure : jauge + pourcentage, avec la même grammaire visuelle pour les trois. */
function Metric({
  id,
  label,
  pct,
  detail,
  warn = false,
}: {
  /** Identifiant STABLE, indépendant de la langue : le libellé est traduit,
   *  s'en servir comme testid rendait les tests dépendants de la locale. */
  id: string
  label: string
  pct: number
  detail: string
  warn?: boolean
}) {
  // Zone de tension intermédiaire : au-delà de trois niveaux la couleur cesse
  // d'informer. Le seuil critique disque vient du serveur ; pour mémoire et CPU
  // on borne ici, faute de seuil métier défini côté portail.
  const tense = !warn && pct >= 75
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 tabular-nums',
        warn ? 'text-destructive font-medium' : tense ? 'text-amber-700' : 'text-muted-foreground',
      )}
      title={detail}
      data-testid={`metric-${id}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="h-1.5 w-6 overflow-hidden rounded-full bg-foreground/10" aria-hidden>
        <span
          className={cn(
            'block h-full rounded-full',
            warn ? 'bg-destructive' : tense ? 'bg-amber-500' : 'bg-foreground/40',
          )}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </span>
      {pct}%
    </span>
  )
}

/**
 * Disque, mémoire et charge CPU d'une machine, sur une ligne sous son nom.
 *
 * Les trois viennent de la MÊME sonde périodique (une connexion SSH) et sont
 * indépendamment optionnels : une machine dont `/proc/meminfo` est illisible
 * affiche quand même son disque. Rien n'est affiché pour une machine jamais
 * sondée — un « 0 % » inventé serait pire que l'absence.
 */
export default function ResourceMetrics({
  disk,
  memory,
  cpu,
}: {
  disk?: DiskUsage
  memory?: MemoryUsage
  cpu?: CpuUsage
}) {
  const { t } = useTranslation()
  if (!disk && !memory && !cpu) return null

  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-normal"
      data-testid="resource-metrics"
    >
      {disk && (
        <Metric
          id="disk"
          label={t('sessions.metrics.disk', { defaultValue: 'Disque' })}
          pct={disk.used_pct}
          warn={disk.warn}
          detail={t('sessions.disk.tooltip', {
            used: formatBytes(disk.used_bytes),
            total: formatBytes(disk.total_bytes),
            free: formatBytes(disk.avail_bytes),
            defaultValue: '{{used}} utilisés sur {{total}} — {{free}} libres',
          })}
        />
      )}
      {memory && (
        <Metric
          id="memory"
          label={t('sessions.metrics.memory', { defaultValue: 'Mém.' })}
          pct={memory.used_pct}
          detail={t('sessions.metrics.memoryTooltip', {
            used: formatBytes(memory.used_bytes),
            total: formatBytes(memory.total_bytes),
            defaultValue: '{{used}} utilisés sur {{total}} (hors cache récupérable)',
          })}
        />
      )}
      {cpu && (
        <Metric
          id="cpu"
          label={t('sessions.metrics.cpu', { defaultValue: 'CPU' })}
          pct={cpu.used_pct}
          detail={t('sessions.metrics.cpuTooltip', {
            cores: cpu.cores ?? '?',
            defaultValue: 'Charge moyenne 1 min sur {{cores}} cœur(s)',
          })}
        />
      )}
    </div>
  )
}
