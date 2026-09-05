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
  /**
   * Cle de contexte dont l'option herite sa valeur quand rien n'est saisi
   * (`from:` dans le manifeste, ex. `workspace.git_url`). Declaree par la
   * recette elle-meme : rien n'est injecte qu'elle n'ait demande.
   */
  from_context?: string | null
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
