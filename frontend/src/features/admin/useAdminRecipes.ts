import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetch, apiFetchJson } from '@/shared/api/client'
import type { Recipe } from '@/features/recipes/types'

export function useAdminRecipes() {
  const qc = useQueryClient()

  const recipesQuery = useQuery<Recipe[]>({
    queryKey: ['admin', 'recipes'],
    queryFn: () => apiFetchJson<Recipe[]>('/admin/recipes'),
    staleTime: 2 * 60 * 1000,
  })

  const deleteRecipe = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/admin/recipes/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'recipes'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  return { recipesQuery, deleteRecipe }
}
