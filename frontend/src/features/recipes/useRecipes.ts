import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import type { Recipe } from './types'

export function useRecipes(type?: 'install' | 'start') {
  return useQuery<Recipe[]>({
    queryKey: ['recipes', type ?? 'all'],
    queryFn: () => apiFetchJson<Recipe[]>(type ? `/recipes?type=${type}` : '/recipes'),
    staleTime: 10 * 60 * 1000,
  })
}
