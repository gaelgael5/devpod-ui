import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { apiFetchJson } from '@/shared/api/client'

export interface RemoteRecipe {
  id: string
  name: string
  description: string
  version: string
  type: 'install' | 'start' | 'initialize'
  source_url: string
  install_script: string
}

/** Une recette installee dont la version publiee a bouge. */
export interface RecipeUpdate {
  id: string
  local_version: string
  remote_version: string
  source_url: string
}

/**
 * Mises a jour disponibles, verifiees a l'affichage de la page.
 *
 * Requete separee et non bloquante : chaque source est interrogee en distant,
 * donc c'est lent et faillible. La liste des recettes locales s'affiche sans
 * attendre ; les boutons « Mettre a jour » apparaissent quand la reponse arrive.
 */
export function useRecipeUpdates() {
  const qc = useQueryClient()
  const { t } = useTranslation()

  const updatesQuery = useQuery<RecipeUpdate[]>({
    queryKey: ['admin', 'recipes', 'updates'],
    queryFn: () => apiFetchJson<RecipeUpdate[]>('/admin/recipes/updates'),
    // Court : l'interet est de refleter ce qui vient d'etre publie.
    staleTime: 30 * 1000,
    retry: false,
  })

  const updateFromSource = useMutation({
    mutationFn: (recipeId: string) =>
      apiFetchJson<{ id: string; version: string }>(
        `/admin/recipes/${encodeURIComponent(recipeId)}/update-from-source`,
        { method: 'POST' },
      ),
    onSuccess: (data) => {
      toast.success(t('admin.recipeUpdated', { id: data.id, version: data.version }))
      qc.invalidateQueries({ queryKey: ['admin', 'recipes'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  return { updatesQuery, updateFromSource }
}

export function useRecipeSources() {
  const qc = useQueryClient()
  const { t } = useTranslation()

  const sourcesQuery = useQuery<{ sources: string[] }>({
    queryKey: ['admin', 'recipe-sources'],
    queryFn: () => apiFetchJson<{ sources: string[] }>('/admin/recipe-sources'),
    staleTime: 5 * 60 * 1000,
  })

  const updateSources = useMutation({
    mutationFn: (sources: string[]) =>
      apiFetchJson<{ sources: string[] }>('/admin/recipe-sources', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'recipe-sources'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  const previewQuery = useQuery<{ recipes: RemoteRecipe[] }>({
    queryKey: ['admin', 'recipe-sources', 'preview'],
    queryFn: () =>
      apiFetchJson<{ recipes: RemoteRecipe[] }>('/admin/recipe-sources/preview'),
    staleTime: 2 * 60 * 1000,
  })

  const importRecipe = useMutation({
    mutationFn: (source_url: string) => {
      // Recette bundlée (source_url = local:<id>) → import local, sinon import distant.
      if (source_url.startsWith('local:')) {
        return apiFetchJson<{ id: string }>('/admin/recipes/import-local', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recipe_id: source_url.slice('local:'.length) }),
        })
      }
      return apiFetchJson<{ id: string }>('/admin/recipe-sources/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url }),
      })
    },
    onSuccess: (data) => {
      toast.success(t('admin.recipeImported', { id: data.id }))
      qc.invalidateQueries({ queryKey: ['admin', 'recipes'] })
      qc.invalidateQueries({ queryKey: ['admin', 'recipe-sources', 'preview'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  return { sourcesQuery, updateSources, previewQuery, importRecipe }
}
