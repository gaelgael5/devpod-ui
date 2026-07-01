export type ComposeParamType = 'string' | 'number' | 'bool' | 'enum' | 'port' | 'secret'
export type TemplateSource = 'user' | 'builtin' | 'imported'
export type DeploymentStatus = 'created' | 'running' | 'partial' | 'stopped' | 'error'

export interface ComposeParam {
  key: string
  label: string
  description?: string | null
  type: ComposeParamType
  default?: string | null
  required: boolean
  options?: string[] | null
  secret_ref_hint?: string | null
}

export interface ComposeTemplate {
  id: string
  name: string
  description: string
  tags: string[]
  version: string
  compose_content: string
  parameters: ComposeParam[]
  source: TemplateSource
  message_key?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface ComposeDeployment {
  uid: string    // UUID PK — utilisé dans les URL API
  id: string     // slug utilisateur — affiché dans l'UI
  template_id: string
  template_version: string
  node_id: string
  owner_login: string
  env_values: Record<string, string>
  host_ports: number[]
  status: DeploymentStatus
  last_error?: string | null
  message_id?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DeploymentMessage {
  id: number | null
  owner_login: string
  workspace_name: string
  type: string
  message: string
  created_at: string | null
}

export interface NodeRef {
  node_id: string
  name: string
  usage?: 'workspaces' | 'tests'
  owner_login?: string
  workspace_name?: string
  alias?: string
}

export interface TemplateBody {
  name: string
  description: string
  tags: string[]
  version: string
  compose_content: string
  parameters: ComposeParam[]
  source: TemplateSource
  message_key: string | null
}

export interface DeploymentCreateBody {
  template_id: string
  node_id: string
  name: string
  env_values: Record<string, string>
}

export interface TemplateSaveResult {
  template: ComposeTemplate
  warnings: string[]
}

export interface PortConflictDetail {
  error: string
  conflicts: number[]
  suggestion: number | null
}
