import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import type { Recipe } from './types'

async function fetchAllRecipes(): Promise<Recipe[]> {
  const [shared, personal] = await Promise.all([
    apiFetchJson<Recipe[]>('/recipes'),
    apiFetchJson<Recipe[]>('/me/recipes'),
  ])
  // personal overrides shared at same id
  const map = new Map(shared.map((r) => [r.id, r]))
  for (const r of personal) map.set(r.id, r)
  return Array.from(map.values())
}

export function useRecipes() {
  return useQuery<Recipe[]>({
    queryKey: ['recipes'],
    queryFn: fetchAllRecipes,
    staleTime: 10 * 60 * 1000,
  })
}
