export interface SecretRef {
  path: string
  env: string
}

export interface Recipe {
  id: string
  key: string
  version: string
  description: string
  type: 'install' | 'start'
  scope: 'builtin' | 'shared' | 'user'
  installs_after: string[]
  requires_secrets: SecretRef[]
  install_script?: string
  builtin?: boolean
}
