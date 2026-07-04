import { describe, it, expect } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import i18n from '@/i18n'
import { useWorkspaceOps } from './useWorkspaceOps'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
    </QueryClientProvider>
  )
}

describe('deleteWorkspace', () => {
  it('résout en succès quand les deux appels (delete puis DELETE config) réussissent', async () => {
    server.use(
      http.post('/me/workspaces/:name/delete', () =>
        HttpResponse.json({ deleted: true, recovery_branch: null }),
      ),
      http.delete('/me/workspaces/:name', () => new HttpResponse(null, { status: 204 })),
    )
    const { result } = renderHook(() => useWorkspaceOps(), { wrapper })
    result.current.deleteWorkspace.mutate({ name: 'app' })
    await waitFor(() => expect(result.current.deleteWorkspace.isSuccess).toBe(true))
  })

  it(
    'bug 019 : si le second appel (DELETE /me/workspaces/:name) échoue, la mutation passe en ' +
      'isError au lieu de se résoudre en succès (état partiel masqué)',
    async () => {
      server.use(
        http.post('/me/workspaces/:name/delete', () =>
          HttpResponse.json({ deleted: true, recovery_branch: null }),
        ),
        http.delete(
          '/me/workspaces/:name',
          () => new HttpResponse('erreur interne', { status: 500, statusText: 'Internal Server Error' }),
        ),
      )
      const { result } = renderHook(() => useWorkspaceOps(), { wrapper })
      result.current.deleteWorkspace.mutate({ name: 'app' })
      await waitFor(() => expect(result.current.deleteWorkspace.isError).toBe(true))
    },
  )
})
