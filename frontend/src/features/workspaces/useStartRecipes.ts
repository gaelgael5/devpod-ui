import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface StartRecipe {
  id: string
  version: string
  description: string
  type: 'start'
}

export function useStartRecipes() {
  return useQuery<StartRecipe[]>({
    queryKey: ['recipes', 'start'],
    queryFn: () => apiFetchJson<StartRecipe[]>('/recipes?type=start'),
    staleTime: 10 * 60 * 1000,
  })
}
