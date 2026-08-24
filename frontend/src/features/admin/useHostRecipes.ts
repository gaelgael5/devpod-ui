import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface HostRecipe {
  id: string
  version: string
  description: string
}

export interface InstalledRecipe {
  version: string
  applied_at: string
}

export interface HostRecipesResponse {
  /** Ce que la MACHINE dit porter — vide si elle est injoignable. */
  installed: Record<string, InstalledRecipe>
  /** Recettes du catalogue déclarant la famille de cette machine. */
  available: HostRecipe[]
}

/**
 * Base d'URL des recettes d'une machine.
 *
 * Avec un workspace, on passe par `/me` : poser une recette de la galerie sur
 * SA machine de test n'a pas a passer par un administrateur — c'est sa machine,
 * et la garde cote serveur est la PROPRIETE, pas le role. Sans workspace, on
 * est dans l'administration des hosts, ou la garde est le role.
 */
function basePath(hostName: string | null, wsName?: string): string {
  const host = encodeURIComponent(hostName ?? '')
  return wsName
    ? `/me/workspaces/${encodeURIComponent(wsName)}/test-hosts/${host}/recipes`
    : `/admin/hosts/${host}/recipes`
}

export function useHostRecipes(hostName: string | null, wsName?: string) {
  return useQuery({
    queryKey: ['host-recipes', wsName ?? null, hostName],
    queryFn: () => apiFetchJson<HostRecipesResponse>(basePath(hostName, wsName)),
    enabled: !!hostName,
  })
}

export function useApplyHostRecipe(hostName: string | null, wsName?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ recipeId, options }: { recipeId: string; options?: Record<string, string> }) =>
      apiFetchJson<{ operation_id: string }>(
        `${basePath(hostName, wsName)}/${encodeURIComponent(recipeId)}`,
        { method: 'POST', body: JSON.stringify({ options: options ?? {} }) },
      ),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['host-recipes', wsName ?? null, hostName] }),
  })
}

/**
 * Suit une opération jusqu'à son terme.
 *
 * Une recette de host peut peser 20 Go : sans ce suivi, l'interface lancerait
 * l'installation sans jamais dire si elle a abouti.
 */
export function useOperation(operationId: string | null) {
  return useQuery({
    queryKey: ['operation', operationId],
    queryFn: () =>
      apiFetchJson<{ state: string; progress: number; error: string | null }>(
        `/admin/operations/${encodeURIComponent(operationId ?? '')}`,
      ),
    enabled: !!operationId,
    // On s'arrête de sonder dès que l'opération est terminée : continuer
    // interrogerait le serveur indéfiniment pour un résultat figé.
    refetchInterval: (query) => {
      const state = query.state.data?.state
      return state === 'done' || state === 'failed' ? false : 3_000
    },
  })
}
