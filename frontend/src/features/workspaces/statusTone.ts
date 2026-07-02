/**
 * Palette de badges de statut partagée entre les workspaces et les déploiements
 * compose — un seul jeu de classes Tailwind pour que "running" ait toujours le
 * même rendu visuel, quel que soit l'endroit où le badge est affiché.
 */
export type StatusTone = 'running' | 'stopped' | 'progress' | 'error' | 'neutral'

export const STATUS_TONE_CLASS: Record<StatusTone, string> = {
  running: 'bg-green-500/10 text-green-600 border-green-500/30',
  stopped: 'bg-yellow-500/10 text-yellow-600 border-yellow-500/30',
  progress: 'bg-primary/10 text-primary border-primary/30',
  error: 'bg-destructive/10 text-destructive border-destructive/30',
  neutral: 'bg-muted text-muted-foreground border-border',
}
