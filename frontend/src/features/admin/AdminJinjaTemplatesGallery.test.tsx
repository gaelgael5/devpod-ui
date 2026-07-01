import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminJinjaTemplates from './AdminJinjaTemplates'

describe('AdminJinjaTemplates — galerie', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
  })

  it('affiche le titre de la galerie', () => {
    renderWithProviders(<AdminJinjaTemplates />)
    expect(
      screen.getByRole('heading', { name: /galerie de templates|template gallery/i }),
    ).toBeInTheDocument()
  })

  it('affiche un bouton Exporter', () => {
    renderWithProviders(<AdminJinjaTemplates />)
    expect(screen.getByRole('button', { name: /exporter|export/i })).toBeInTheDocument()
  })

  it("ajoute une source via le champ texte", async () => {
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')
    const captured: unknown[] = []
    server.use(
      http.put('/admin/jinja-template-sources', async ({ request }) => {
        const body = await request.json()
        captured.push(body)
        return HttpResponse.json(body)
      }),
    )
    renderWithProviders(<AdminJinjaTemplates />)
    const input = screen.getByPlaceholderText(/jinja\/toc\.txt/i)
    await userEvent.type(input, 'https://example.com/jinja/toc.txt')
    await userEvent.click(screen.getByRole('button', { name: /^ajouter$|^add$/i }))
    expect(captured).toHaveLength(1)
    expect((captured[0] as { sources: string[] }).sources).toContain(
      'https://example.com/jinja/toc.txt',
    )
  })
})
