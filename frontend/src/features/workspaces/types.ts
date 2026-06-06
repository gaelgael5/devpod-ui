export interface WorkspaceSpec {
  name: string
  source: string
  host: string
  recipes: string[]
  env: Record<string, string>
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
}

export const TRANSIENT: ReadonlySet<WorkspaceStatusValue> = new Set([
  'provisioning',
])

export function isTransient(s: WorkspaceStatusValue | undefined): boolean {
  return TRANSIENT.has(s as WorkspaceStatusValue)
}
