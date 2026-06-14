import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import type { Recipe } from './types'

export function useRecipes() {
  return useQuery<Recipe[]>({
    queryKey: ['recipes'],
    queryFn: () => apiFetchJson<Recipe[]>('/recipes'),
    staleTime: 10 * 60 * 1000,
  })
}
