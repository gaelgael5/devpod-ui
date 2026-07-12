import { describe, it, expect } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { useVaultReset, vaultQueryKeys } from './api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }
  return { qc, wrapper }
}

describe('useVaultReset', () => {
  it('résout en succès et marque le coffre setup_required quand le backend répond 204', async () => {
    server.use(http.delete('/vault/pin', () => new HttpResponse(null, { status: 204 })))
    const { qc, wrapper } = makeWrapper()
    const { result } = renderHook(() => useVaultReset(), { wrapper })
    result.current.mutate()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(qc.getQueryData(vaultQueryKeys.status())).toEqual({ status: 'setup_required' })
  })

  it(
    'bug 018 (cas aggravé) : un DELETE /vault/pin échoué (500) passe en isError et ne ' +
      "réécrit pas le cache en setup_required — le coffre reste dans son état réel",
    async () => {
      server.use(http.delete('/vault/pin', () => new HttpResponse(null, { status: 500 })))
      const { qc, wrapper } = makeWrapper()
      qc.setQueryData(vaultQueryKeys.status(), { status: 'unlocked' })
      const { result } = renderHook(() => useVaultReset(), { wrapper })
      result.current.mutate()
      await waitFor(() => expect(result.current.isError).toBe(true))
      expect(qc.getQueryData(vaultQueryKeys.status())).toEqual({ status: 'unlocked' })
    },
  )
})
