import { describe, it, expect } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { useDeleteHost } from './useHosts'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useDeleteHost', () => {
  it('résout en succès quand le backend répond 204', async () => {
    server.use(http.delete('/admin/hosts/:name', () => new HttpResponse(null, { status: 204 })))
    const { result } = renderHook(() => useDeleteHost(), { wrapper })
    result.current.mutate('host-1')
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it("bug 018 : passe en isError (au lieu de se résoudre silencieusement) quand le backend répond 409", async () => {
    server.use(
      http.delete(
        '/admin/hosts/:name',
        () => new HttpResponse(JSON.stringify({ detail: 'host en cours d’utilisation' }), {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const { result } = renderHook(() => useDeleteHost(), { wrapper })
    result.current.mutate('host-1')
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error?.message).toContain('utilisation')
  })
})
