/**
 * Suppression d'une machine de test.
 *
 * Le defaut corrige ici : la machine restait affichee ailleurs dans le portail.
 * Elle est listee a trois endroits — la carte du workspace, l'administration
 * des hosts, la page des sessions — et seule la premiere etait rafraichie.
 */
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { createElement } from 'react'
import { server } from '@/test/server'
import { useDeleteTestHost } from './useTestVm'

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  const invalidees: unknown[][] = []
  const original = queryClient.invalidateQueries.bind(queryClient)
  vi.spyOn(queryClient, 'invalidateQueries').mockImplementation((filters) => {
    invalidees.push((filters?.queryKey ?? []) as unknown[])
    return original(filters)
  })
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children)
  return { wrapper, invalidees }
}

describe('useDeleteTestHost', () => {
  it('rafraichit les trois vues qui listent la machine', async () => {
    server.use(
      http.delete('/me/workspaces/:ws/test-vm/:host', () => new HttpResponse(null, { status: 204 })),
    )
    const { wrapper, invalidees } = setup()
    const { result } = renderHook(() => useDeleteTestHost('myapp'), { wrapper })

    result.current.mutate('host-test-1')

    await waitFor(() => expect(invalidees.length).toBeGreaterThanOrEqual(3))
    const plates = invalidees.map((k) => k.join('/'))
    expect(plates).toContain('me/workspaces/myapp/test-hosts')
    // Les deux qui manquaient : la machine restait visible en administration et
    // dans la liste des sessions.
    expect(plates).toContain('admin/hosts')
    expect(plates).toContain('sessions')
  })

  it('ne rafraichit rien quand la suppression echoue', async () => {
    // Invalider sur echec ferait clignoter les listes pour rien, et laisserait
    // croire que quelque chose s'est passe.
    server.use(
      http.delete('/me/workspaces/:ws/test-vm/:host', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )
    const { wrapper, invalidees } = setup()
    const { result } = renderHook(() => useDeleteTestHost('myapp'), { wrapper })

    result.current.mutate('host-test-1')

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(invalidees).toHaveLength(0)
  })
})
