import { screen, within, waitFor } from '@testing-library/react'
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

  /**
   * Installe les handlers MSW communs aux tests d'import/overwrite :
   * - un template déjà présent en base (welcome/fr)
   * - la galerie distante expose ce même template (présent) et un absent (welcome/en)
   */
  async function mockGalleryData() {
    const { server } = await import('@/test/server')
    const { http, HttpResponse } = await import('msw')
    server.use(
      http.get('/admin/jinja-templates', () =>
        HttpResponse.json([{ key: 'welcome', culture: 'fr', body: 'x' }]),
      ),
      http.get('/admin/jinja-template-sources/preview', () =>
        HttpResponse.json({
          templates: [
            {
              filename: 'welcome.fr.j2',
              key: 'welcome',
              culture: 'fr',
              description: 'Message de bienvenue (fr)',
              source_url: 'https://example.com/jinja/welcome.fr.j2',
              source_base: 'https://example.com/jinja',
            },
            {
              filename: 'welcome.en.j2',
              key: 'welcome',
              culture: 'en',
              description: 'Welcome message (en)',
              source_url: 'https://example.com/jinja/welcome.en.j2',
              source_base: 'https://example.com/jinja',
            },
          ],
        }),
      ),
    )
    return { server, http, HttpResponse }
  }

  it("importe directement un template ABSENT avec overwrite:false", async () => {
    const { server, http, HttpResponse } = await mockGalleryData()
    const captured: unknown[] = []
    server.use(
      http.post('/admin/jinja-template-sources/import', async ({ request }) => {
        const body = await request.json()
        captured.push(body)
        return HttpResponse.json(body)
      }),
    )

    renderWithProviders(<AdminJinjaTemplates />)
    const absentCard = (await screen.findByText('Welcome message (en)')).closest('div.rounded-lg')
    expect(absentCard).not.toBeNull()
    const importBtn = within(absentCard as HTMLElement).getByRole('button', {
      name: /^importer$|^import$/i,
    })
    await userEvent.click(importBtn)

    await waitFor(() => expect(captured).toHaveLength(1))
    expect(captured[0]).toMatchObject({ key: 'welcome', culture: 'en', overwrite: false })
  })

  it('affiche le badge "présent" pour un template déjà en base', async () => {
    await mockGalleryData()
    renderWithProviders(<AdminJinjaTemplates />)
    const presentCard = (await screen.findByText('Message de bienvenue (fr)')).closest(
      'div.rounded-lg',
    )
    expect(presentCard).not.toBeNull()
    expect(
      within(presentCard as HTMLElement).getByText(/^présent$|^present$/i),
    ).toBeInTheDocument()
  })

  it("ouvre la confirmation puis importe avec overwrite:true pour un template PRESENT", async () => {
    const { server, http, HttpResponse } = await mockGalleryData()
    const captured: unknown[] = []
    server.use(
      http.post('/admin/jinja-template-sources/import', async ({ request }) => {
        const body = await request.json()
        captured.push(body)
        return HttpResponse.json(body)
      }),
    )

    renderWithProviders(<AdminJinjaTemplates />)
    const presentCard = (await screen.findByText('Message de bienvenue (fr)')).closest(
      'div.rounded-lg',
    )
    expect(presentCard).not.toBeNull()
    const importBtn = within(presentCard as HTMLElement).getByRole('button', {
      name: /^importer$|^import$/i,
    })
    await userEvent.click(importBtn)

    expect(
      await screen.findByText(/écraser le template existant|overwrite existing template/i),
    ).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^écraser$|^overwrite$/i }))

    await waitFor(() => expect(captured).toHaveLength(1))
    expect(captured[0]).toMatchObject({ key: 'welcome', culture: 'fr', overwrite: true })
  })
})
