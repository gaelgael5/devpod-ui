import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface RemoteRecipe {
  id: string
  name: string
  description: string
  version: string
  source_url: string
  install_script: string
}

export function useRecipeSources() {
  const qc = useQueryClient()

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
    mutationFn: (source_url: string) =>
      apiFetchJson<{ id: string }>('/admin/recipe-sources/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_url }),
      }),
    onSuccess: (data) => {
      toast.success(`Recette "${data.id}" importée`)
      qc.invalidateQueries({ queryKey: ['admin', 'recipes'] })
      qc.invalidateQueries({ queryKey: ['admin', 'recipe-sources', 'preview'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  return { sourcesQuery, updateSources, previewQuery, importRecipe }
}
