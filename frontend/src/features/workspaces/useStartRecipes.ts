import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import type { Recipe } from '@/features/recipes/types'

export function useStartRecipes() {
  return useQuery<Recipe[]>({
    queryKey: ['recipes', 'start'],
    queryFn: () => apiFetchJson<Recipe[]>('/recipes?type=start'),
    staleTime: 10 * 60 * 1000,
  })
}
