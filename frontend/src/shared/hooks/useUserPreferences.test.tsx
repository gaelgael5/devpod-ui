import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { useSetPreference, useUserPreferences } from './useUserPreferences'

function wrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

describe('useUserPreferences', () => {
  it('charge la map de préférences', async () => {
    server.use(
      http.get('/me/preferences', () =>
        HttpResponse.json({ 'workspaces.group.3.collapse': true }),
      ),
    )
    const { result } = renderHook(() => useUserPreferences(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({ 'workspaces.group.3.collapse': true })
  })

  it('PUT envoie un corps typé discriminé et met à jour de façon optimiste', async () => {
    let captured: { url: string; body: unknown } | null = null
    server.use(
      http.get('/me/preferences', () => HttpResponse.json({})),
      http.put('/me/preferences/:key', async ({ request }) => {
        captured = { url: request.url, body: await request.json() }
        return new HttpResponse(null, { status: 204 })
      }),
    )

    const { result } = renderHook(
      () => ({ prefs: useUserPreferences(), set: useSetPreference() }),
      { wrapper: wrapper() },
    )
    await waitFor(() => expect(result.current.prefs.isSuccess).toBe(true))

    result.current.set.mutate({ key: 'workspaces.group.ungrouped.collapse', value: true })

    // Optimiste : le cache reflète la valeur avant même la réponse réseau.
    await waitFor(() =>
      expect(result.current.prefs.data?.['workspaces.group.ungrouped.collapse']).toBe(true),
    )
    await waitFor(() => expect(captured).not.toBeNull())
    expect(captured!.body).toEqual({ bool: true }) // booléen → colonne bool
    expect(captured!.url).toContain('/me/preferences/workspaces.group.ungrouped.collapse')
  })
})
