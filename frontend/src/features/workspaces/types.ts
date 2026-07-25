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
}

export const TRANSIENT: ReadonlySet<WorkspaceStatusValue> = new Set([
  'provisioning',
  'failed',
  'unknown',
])

export function isTransient(s: WorkspaceStatusValue | undefined): boolean {
  return TRANSIENT.has(s as WorkspaceStatusValue)
}
