export interface SecretRef {
  path: string
  env: string
}

export interface MemoryVolumeSpec {
  name: string
  optional: boolean
  mapping: { target: string }
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
  memory_volume?: MemoryVolumeSpec | null
}
