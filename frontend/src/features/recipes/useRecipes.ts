import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'
import type { Recipe } from './types'

export function useRecipes(type?: 'install' | 'start' | 'initialize') {
  return useQuery<Recipe[]>({
    queryKey: ['recipes', type ?? 'all'],
    queryFn: () => apiFetchJson<Recipe[]>(type ? `/recipes?type=${type}` : '/recipes'),
    staleTime: 10 * 60 * 1000,
  })
}

export interface UserRecipeCreateBody {
  id: string
  version: string
  description: string
  type: 'install' | 'start'
  install_script: string
}

export interface UserRecipeUpdateBody {
  id: string
  version: string
  description: string
  install_script: string
}

export function useForkRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (recipeId: string) =>
      apiFetchJson<Recipe>(`/me/recipes/${encodeURIComponent(recipeId)}/fork`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['recipes'] })
    },
  })
}

export function useCreateUserRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UserRecipeCreateBody) =>
      apiFetchJson<Recipe>('/me/recipes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['recipes'] })
    },
  })
}

export function useUpdateUserRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: UserRecipeUpdateBody) =>
      apiFetchJson<Recipe>(`/me/recipes/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['recipes'] })
    },
  })
}

export function useDeleteUserRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (recipeId: string) =>
      apiFetch(`/me/recipes/${encodeURIComponent(recipeId)}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['recipes'] })
    },
  })
}
