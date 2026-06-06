export interface SecretRef {
  path: string
  env: string
}

export interface Recipe {
  id: string
  version: string
  description: string
  installs_after: string[]
  requires_secrets: SecretRef[]
}
