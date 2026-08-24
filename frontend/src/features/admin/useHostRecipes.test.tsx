/**
 * Corps de la requête d'application.
 *
 * Deux regles, nees du meme 422 « Input should be a valid dictionary » : pas
 * de corps quand il n'y a rien a dire, et un `Content-Type` des qu'il y en a
 * un — sans quoi FastAPI le recoit comme une CHAINE.
 */
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { server } from '@/test/server'
import { useApplyHostRecipe } from './useHostRecipes'

function wrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

function capture() {
  const vu: { brut?: string; type?: string | null } = {}
  server.use(
    http.post('/admin/hosts/:name/recipes/:id', async ({ request }) => {
      vu.type = request.headers.get('content-type')
      vu.brut = await request.text()
      return HttpResponse.json({ operation_id: 'op-1' }, { status: 202 })
    }),
  )
  return vu
}

describe('useApplyHostRecipe', () => {
  it('n’envoie aucun corps sans option', async () => {
    const vu = capture()
    const { result } = renderHook(() => useApplyHostRecipe('test1'), { wrapper: wrapper() })

    result.current.mutate({ recipeId: 'android-emulator' })

    await waitFor(() => expect(vu.brut).toBe(''))
  })

  it('n’envoie aucun corps pour un objet d’options vide', async () => {
    // `{}` ne dit rien de plus que rien : autant ne pas l'envoyer.
    const vu = capture()
    const { result } = renderHook(() => useApplyHostRecipe('test1'), { wrapper: wrapper() })

    result.current.mutate({ recipeId: 'android-emulator', options: {} })

    await waitFor(() => expect(vu.brut).toBe(''))
  })

  it('déclare le type du corps quand il y a des options', async () => {
    const vu = capture()
    const { result } = renderHook(() => useApplyHostRecipe('test1'), { wrapper: wrapper() })

    result.current.mutate({ recipeId: 'android-emulator', options: { api_level: '34' } })

    await waitFor(() => expect(vu.type).toMatch(/application\/json/))
    expect(JSON.parse(vu.brut ?? '{}')).toEqual({ options: { api_level: '34' } })
  })
})
