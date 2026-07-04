import { describe, it, expect } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { useDestroyVm } from './useHosts'

function streamHandler(onSignal: (signal: AbortSignal) => void) {
  return http.post('/admin/hypervisors/:name/execute-destroy', ({ request }) => {
    onSignal(request.signal)
    // Stream qui ne se termine jamais dans la fenêtre du test — simule un
    // destroy encore en cours quand le composant se démonte.
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('==> destroying\n'))
      },
    })
    return new HttpResponse(stream, { headers: { 'Content-Type': 'text/plain' } })
  })
}

describe('useDestroyVm', () => {
  it('résout logs + done quand le stream se termine normalement', async () => {
    server.use(
      http.post(
        '/admin/hypervisors/:name/execute-destroy',
        () => new HttpResponse('==> ok\n', { status: 200 }),
      ),
    )
    const { result } = renderHook(() => useDestroyVm())
    await act(async () => {
      await result.current.execute('node1', '100')
    })
    expect(result.current.done).toBe(true)
    expect(result.current.error).toBeNull()
    expect(result.current.logs).toBe('==> ok\n')
  })

  it(
    "bug 020 : annule le fetch (AbortSignal) au démontage du hook, au lieu de laisser " +
      'le backend streamer dans le vide',
    async () => {
      let capturedSignal: AbortSignal | undefined
      server.use(streamHandler((s) => { capturedSignal = s }))
      const { result, unmount } = renderHook(() => useDestroyVm())

      let executePromise: Promise<void>
      act(() => {
        executePromise = result.current.execute('node1', '100')
      })
      await waitFor(() => expect(capturedSignal).toBeDefined())
      await waitFor(() => expect(result.current.running).toBe(true))

      unmount()
      await waitFor(() => expect(capturedSignal?.aborted).toBe(true))
      await executePromise!
    },
  )
})
