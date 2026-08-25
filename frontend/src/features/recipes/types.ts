export interface SecretRef {
  path: string
  env: string
}

export interface MemoryVolumeSpec {
  name: string
  optional: boolean
  mapping: { target: string }
}

/** Une option declaree par une recette : ce qu'un profil peut y regler. */
export interface RecipeOption {
  type: string
  default: string
  description: string
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
  options?: Record<string, RecipeOption>
}
