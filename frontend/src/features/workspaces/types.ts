export interface SourceSpec {
  url: string
  branch: string
  git_credential: string
}

export interface WorkspaceSpec {
  name: string
  source: string
  branch: string
  git_credential: string
  host: string
  recipes: string[]
  env: Record<string, string>
  extra_sources: SourceSpec[]
  ssh_key?: boolean
  profile?: { scope: 'shared' | 'user'; slug: string } | null
  start_recipes?: string[]
  default_start?: string
  recipe_volumes?: string[]
  init_recipes?: string[]
  groups?: string[]
  // Ids de types d'agents IA avec accès MCP direct (spec 35).
  agents?: string[]
  // Épingle « garder actif » : jamais de suggestion d'arrêt pour inactivité (6016436b).
  keep_active?: boolean
  // Surcharge de la limite mémoire du conteneur (59864c37), "" = défaut global.
  memory_limit?: string
}

export type WorkspaceStatusValue =
  | 'provisioning'
  | 'running'
  | 'stopped'
  | 'failed'
  | 'unknown'

export interface WorkspaceStatus {
  ws_id: string
  status: WorkspaceStatusValue
  url?: string
  host_port?: number
  returncode?: number
  login?: string
  /** Verdict de réachabilité dérivé des sondes (running uniquement) :
   false = host injoignable — le statut `running` est alors déclaratif, pas réel
   (bug 2846f916). null/absent = pas de verdict récent. */
  reachable?: boolean | null
  /** Épingle « garder actif » (6016436b) : jamais de suggestion d'arrêt. */
  keep_active?: boolean
  /** Début de la période d'inactivité continue observée (ISO). */
  idle_since?: string
  /** Inactif au-delà du seuil : proposer l'arrêt (jamais automatique). */
  stop_suggested?: boolean
}

export const TRANSIENT: ReadonlySet<WorkspaceStatusValue> = new Set([
  'provisioning',
  'failed',
  'unknown',
])

export function isTransient(s: WorkspaceStatusValue | undefined): boolean {
  return TRANSIENT.has(s as WorkspaceStatusValue)
}
