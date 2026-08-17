import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import type { WorkspaceSpec } from './types'

/** Champs éditables après création. `name` en est absent : le renommer changerait
 *  le ws_id, donc l'identité du conteneur — ce n'est pas une édition de config. */
export interface WorkspacePatch {
  source?: string
  branch?: string
  git_credential?: string
  host?: string
  recipes?: string[]
  start_recipes?: string[]
  init_recipes?: string[]
  recipe_volumes?: string[]
  profile?: { scope: 'shared' | 'user'; slug: string } | null
  agents?: string[]
  memory_limit?: string
  ssh_key?: boolean
  default_start?: string
}

/**
 * Impact d'une édition, calculé par le SERVEUR (source de vérité unique :
 * `devpod/spec_changes.py`). L'UI ne re-devine pas la règle de son côté.
 */
export interface WorkspacePatchResult {
  spec: WorkspaceSpec
  /** Champs qui n'auront d'effet qu'après reconstruction de l'image. */
  requires_recreate: string[]
  /** Champs appliqués au prochain `up` (un stop/start suffit). */
  requires_restart: string[]
  /** Recettes ajoutées — le cas le plus courant de recréation nécessaire. */
  added_recipes: string[]
}

/** Édite la config d'un workspace existant. Ne redémarre ni ne recrée rien :
 *  la décision revient à l'utilisateur (une recréation détruit le travail non
 *  commité), l'appelant lit `requires_recreate` pour l'en avertir. */
export function useUpdateWorkspace(name: string) {
  const qc = useQueryClient()
  return useMutation<WorkspacePatchResult, Error, WorkspacePatch>({
    mutationFn: (patch) =>
      apiFetchJson<WorkspacePatchResult>(`/me/workspaces/${encodeURIComponent(name)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })
}
