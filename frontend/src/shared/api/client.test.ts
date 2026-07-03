import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { ApiError, apiFetchJson } from './client'

describe('apiFetchJson error extraction', () => {
  it('utilise le detail JSON (contrat FastAPI)', async () => {
    server.use(
      http.get('/boom', () => HttpResponse.json({ detail: 'workspace introuvable' }, { status: 404 })),
    )
    await expect(apiFetchJson('/boom')).rejects.toMatchObject({
      message: 'workspace introuvable',
      status: 404,
    })
  })

  it('retombe sur statusText face à une page HTML de proxy (Cloudflare 502)', async () => {
    const html =
      '<!DOCTYPE html><html><body><h1>Bad gateway</h1>' + '<p>lots of markup</p>'.repeat(50) + '</body></html>'
    server.use(
      http.get('/boom', () => new HttpResponse(html, { status: 502, statusText: 'Bad Gateway' })),
    )
    const err = await apiFetchJson('/boom').catch((e: unknown) => e as ApiError)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).message).toBe('Bad Gateway')
    expect((err as ApiError).message).not.toContain('<html>')
  })

  it('tronque un corps texte brut trop long', async () => {
    const longText = 'x'.repeat(1000)
    server.use(http.get('/boom', () => new HttpResponse(longText, { status: 500 })))
    const err = await apiFetchJson('/boom').catch((e: unknown) => e as ApiError)
    expect((err as ApiError).message.length).toBeLessThan(320)
    expect((err as ApiError).message.endsWith('…')).toBe(true)
  })

  it('retombe sur statusText si le corps est vide', async () => {
    server.use(
      http.get('/boom', () => new HttpResponse('', { status: 503, statusText: 'Service Unavailable' })),
    )
    const err = await apiFetchJson('/boom').catch((e: unknown) => e as ApiError)
    expect((err as ApiError).message).toBe('Service Unavailable')
  })
})
