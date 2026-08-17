import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import type { DiskUsage } from './useSessions'
import { formatBytes } from './formatBytes'

/**
 * Ratio d'occupation disque d'une machine (host, serveur de ressources, VM de test).
 *
 * Affiché dans la fenêtre sessions. Trois seuils visuels seulement — au-delà,
 * la couleur cesse d'informer : normal, tendu (≥ 75 %), critique (seuil serveur,
 * 90 % par défaut). C'est le SERVEUR qui décide de `warn` : l'UI ne recalcule
 * pas le seuil de son côté, sinon les deux divergent le jour où il change.
 */
export default function DiskUsageBadge({ disk }: { disk: DiskUsage }) {
  const { t } = useTranslation()
  const pct = disk.used_pct
  const tense = pct >= 75 && !disk.warn

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs tabular-nums',
        disk.warn
          ? 'bg-destructive/10 text-destructive font-medium'
          : tense
            ? 'bg-amber-500/10 text-amber-700'
            : 'bg-muted text-muted-foreground',
      )}
      data-testid="disk-usage"
      title={t('sessions.disk.tooltip', {
        used: formatBytes(disk.used_bytes),
        total: formatBytes(disk.total_bytes),
        free: formatBytes(disk.avail_bytes),
        defaultValue: '{{used}} utilisés sur {{total}} — {{free}} libres',
      })}
    >
      {/* Jauge : lisible d'un coup d'œil, sans dépendre de la couleur seule. */}
      <span className="h-1.5 w-8 overflow-hidden rounded-full bg-foreground/10" aria-hidden>
        <span
          className={cn(
            'block h-full rounded-full',
            disk.warn ? 'bg-destructive' : tense ? 'bg-amber-500' : 'bg-foreground/40',
          )}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </span>
      {pct}%
      <span className="text-[0.9em] opacity-75">
        {t('sessions.disk.free', {
          free: formatBytes(disk.avail_bytes),
          defaultValue: '({{free}} libres)',
        })}
      </span>
    </span>
  )
}
