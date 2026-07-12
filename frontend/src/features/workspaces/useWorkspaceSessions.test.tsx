import { describe, it, expect } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { useWorkspaceSessions, useCreateSession, useDeleteSession } from './useWorkspaceSessions'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('bug 044 : encodage URL wsName/sessionName', () => {
  it('encode wsName dans le GET de la liste des sessions', async () => {
    let capturedUrl = ''
    server.use(
      http.get('/me/workspaces/:name/sessions', ({ request }) => {
        capturedUrl = new URL(request.url).pathname
        return HttpResponse.json(['s1'])
      })
    )
    const { result } = renderHook(() => useWorkspaceSessions('my app/../x'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(capturedUrl).toBe('/me/workspaces/my%20app%2F..%2Fx/sessions')
  })

  it('encode wsName dans le POST de création de session', async () => {
    let capturedUrl = ''
    server.use(
      http.post('/me/workspaces/:name/sessions', ({ request }) => {
        capturedUrl = new URL(request.url).pathname
        return HttpResponse.json({ name: 's1' }, { status: 201 })
      })
    )
    const { result } = renderHook(() => useCreateSession(), { wrapper })
    result.current.mutate({ wsName: 'my app/x', name: 's1' })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(capturedUrl).toBe('/me/workspaces/my%20app%2Fx/sessions')
  })

  it('encode wsName et sessionName dans le DELETE', async () => {
    let capturedUrl = ''
    server.use(
      http.delete('/me/workspaces/:name/sessions/:session', ({ request }) => {
        capturedUrl = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      })
    )
    const { result } = renderHook(() => useDeleteSession(), { wrapper })
    result.current.mutate({ wsName: 'my app', sessionName: 's/1#x' })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(capturedUrl).toBe('/me/workspaces/my%20app/sessions/s%2F1%23x')
  })
})
