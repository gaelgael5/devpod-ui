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

export function useHostRecipes(hostName: string | null) {
  return useQuery({
    queryKey: ['host-recipes', hostName],
    queryFn: () =>
      apiFetchJson<HostRecipesResponse>(
        `/admin/hosts/${encodeURIComponent(hostName ?? '')}/recipes`,
      ),
    enabled: !!hostName,
  })
}

export function useApplyHostRecipe(hostName: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ recipeId, options }: { recipeId: string; options?: Record<string, string> }) =>
      apiFetchJson<{ operation_id: string }>(
        `/admin/hosts/${encodeURIComponent(hostName ?? '')}/recipes/${encodeURIComponent(recipeId)}`,
        { method: 'POST', body: JSON.stringify({ options: options ?? {} }) },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['host-recipes', hostName] }),
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
