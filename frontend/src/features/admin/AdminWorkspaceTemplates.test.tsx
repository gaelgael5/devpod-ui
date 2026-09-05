/**
 * Galerie admin des templates de workspace.
 *
 * Ce qui est verrouillé : un brouillon s'affiche comme tel, l'enregistrement
 * envoie le preset complet (recettes, clef SSH, publication) sous le slug de
 * l'URL, et un slug invalide est bloqué à la saisie.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Toaster } from 'sonner'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import i18n from '@/i18n'
import AdminWorkspaceTemplates from './AdminWorkspaceTemplates'

let corpsEnvoye: unknown
let slugEnvoye = ''

const TEMPLATE = {
  slug: 'python-ia',
  label: 'Python + IA',
  description: '',
  published: false,
  spec: {
    branch: 'dev',
    recipes: ['python'],
    start_recipes: [],
    init_recipes: [],
    recipe_volumes: [],
    default_start: '',
    agents: ['claude'],
    profile: null,
    memory_limit: '8g',
    ssh_key: true,
    ide: '',
    env: {},
  },
}

function servir(templates: unknown[] = [TEMPLATE]) {
  corpsEnvoye = undefined
  slugEnvoye = ''
  server.use(
    http.get('/admin/workspace-templates', () => HttpResponse.json(templates)),
    http.put('/admin/workspace-templates/:slug', async ({ request, params }) => {
      slugEnvoye = String(params.slug)
      corpsEnvoye = await request.json()
      return HttpResponse.json({ slug: slugEnvoye, ...(corpsEnvoye as object) })
    }),
    http.get('/recipes', () => HttpResponse.json([])),
    http.get('/me/agent-types', () => HttpResponse.json([])),
    http.get('/profiles', () => HttpResponse.json([])),
  )
}

describe('AdminWorkspaceTemplates', () => {
  it('liste la galerie et marque les brouillons', async () => {
    servir()
    renderWithProviders(<AdminWorkspaceTemplates />)

    expect(await screen.findByText('Python + IA')).toBeInTheDocument()
    expect(screen.getByText(i18n.t('adminWsTemplates.draft'))).toBeInTheDocument()
  })

  it('enregistre un nouveau template sous le slug saisi, preset compris', async () => {
    servir([])
    renderWithProviders(
      <>
        <Toaster />
        <AdminWorkspaceTemplates />
      </>,
    )

    await userEvent.click(
      await screen.findByRole('button', { name: i18n.t('adminWsTemplates.new') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('adminWsTemplates.slug')), 'node-web')
    await userEvent.type(screen.getByLabelText(i18n.t('adminWsTemplates.label')), 'Node web')
    await userEvent.click(screen.getByLabelText(i18n.t('adminWsTemplates.sshKey')))
    await userEvent.click(screen.getByLabelText(i18n.t('adminWsTemplates.published')))
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(await screen.findByText(i18n.t('adminWsTemplates.saved'))).toBeInTheDocument()
    expect(slugEnvoye).toBe('node-web')
    expect(corpsEnvoye).toMatchObject({
      label: 'Node web',
      published: true,
      spec: expect.objectContaining({ ssh_key: true }),
    })
  })

  it('bloque un slug invalide à la saisie', async () => {
    servir([])
    renderWithProviders(<AdminWorkspaceTemplates />)

    await userEvent.click(
      await screen.findByRole('button', { name: i18n.t('adminWsTemplates.new') }),
    )
    await userEvent.type(screen.getByLabelText(i18n.t('adminWsTemplates.slug')), 'Mauvais_Slug')
    await userEvent.click(screen.getByRole('button', { name: i18n.t('common.save') }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      i18n.t('adminWsTemplates.slugHint'),
    )
    expect(corpsEnvoye).toBeUndefined()
  })
})
