import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import RulesTab from './RulesTab'

const SERVICE = {
  id: 's1',
  owner_login: 'alice',
  name: 'Docflow',
  url: 'https://docflow.example.org',
  mcp_profile_id: 'p1',
  mcp_profile_name: 'Ops',
  created_at: '2026-07-05T00:00:00Z',
  updated_at: null,
}

const TOOLS = [
  { name: 'docflow__list_workspaces', description: 'liste', input_schema: {} },
  { name: 'docflow__create_workspace', description: 'crée', input_schema: {} },
]

const RULE = {
  id: 'r1',
  owner_login: 'alice',
  name: 'Créer le workspace docflow',
  enabled: true,
  event_type: 'workspace.created',
  probe_service_id: 's1',
  probe_tool: 'docflow__list_workspaces',
  probe_args: {},
  condition_path: 'slug',
  condition_operator: 'not_contains' as const,
  condition_value: '{workspace}',
  action_service_id: 's1',
  action_tool: 'docflow__create_workspace',
  action_args: { slug: '{workspace}', label: '{workspace}' },
  created_at: '2026-07-05T00:00:00Z',
  updated_at: null,
}

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('RulesTab', () => {
  it('affiche les règles avec leur événement déclencheur', async () => {
    server.use(
      http.get('/me/rules', () => HttpResponse.json([RULE])),
      http.get('/me/rules/events', () => HttpResponse.json(['workspace.created'])),
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
    )
    renderWithProviders(<RulesTab />)
    expect(await screen.findByText('Créer le workspace docflow')).toBeInTheDocument()
    expect(screen.getByText('workspace.created')).toBeInTheDocument()
    expect(screen.getByText(/docflow__list_workspaces/)).toBeInTheDocument()
  })

  it("affiche l'état vide", async () => {
    server.use(
      http.get('/me/rules', () => HttpResponse.json([])),
      http.get('/me/rules/events', () => HttpResponse.json([])),
      http.get('/me/services', () => HttpResponse.json([])),
    )
    renderWithProviders(<RulesTab />)
    expect(await screen.findByText(/aucune règle|no rule yet/i)).toBeInTheDocument()
  })

  it('crée une règle complète (POST)', async () => {
    let posted: unknown = null
    server.use(
      http.get('/me/rules', () => HttpResponse.json([])),
      http.get('/me/rules/events', () =>
        HttpResponse.json(['workspace.created', 'workspace.deleted']),
      ),
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
      http.get('/me/services/s1/tools', () => HttpResponse.json(TOOLS)),
      http.post('/me/rules', async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json({ id: 'new' }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<RulesTab />)

    await user.click(await screen.findByRole('button', { name: /ajouter une règle|add a rule/i }))
    await user.type(screen.getByLabelText(/^nom$|^name$/i), 'Ma règle')

    // Événement déclencheur
    await user.click(screen.getByLabelText(/événement déclencheur|trigger event/i))
    await user.click(await screen.findByRole('option', { name: 'workspace.created' }))

    // Sonde : service puis méthode
    const serviceSelects = screen.getAllByLabelText(/^service$/i)
    await user.click(serviceSelects[0])
    await user.click(await screen.findByRole('option', { name: 'Docflow' }))
    const toolSelects = screen.getAllByLabelText(/méthode mcp|mcp method/i)
    await user.click(toolSelects[0])
    await user.click(await screen.findByRole('option', { name: 'docflow__list_workspaces' }))

    // Condition
    await user.type(screen.getByLabelText(/chemin d'extraction|extraction path/i), 'slug')
    await user.type(
      screen.getByLabelText(/valeur comparée|compared value/i),
      '{{workspace}',
    )

    // Action : service puis méthode
    await user.click(serviceSelects[1])
    await user.click(await screen.findByRole('option', { name: 'Docflow' }))
    await user.click(toolSelects[1])
    await user.click(await screen.findByRole('option', { name: 'docflow__create_workspace' }))

    await user.click(screen.getByRole('button', { name: /enregistrer|save/i }))

    await waitFor(() =>
      expect(posted).toEqual({
        name: 'Ma règle',
        enabled: true,
        event_type: 'workspace.created',
        probe: { service_id: 's1', tool: 'docflow__list_workspaces', args: {} },
        condition: { path: 'slug', operator: 'not_contains', value: '{workspace}' },
        action: { service_id: 's1', tool: 'docflow__create_workspace', args: {} },
      }),
    )
  })

  it('joue une règle et affiche la trace', async () => {
    let testedBody: unknown = null
    server.use(
      http.get('/me/rules', () => HttpResponse.json([RULE])),
      http.get('/me/rules/events', () => HttpResponse.json(['workspace.created'])),
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
      http.post('/me/rules/r1/test', async ({ request }) => {
        testedBody = await request.json()
        return HttpResponse.json({
          ok: true,
          rule: RULE.name,
          matched: true,
          probe: { tool: RULE.probe_tool, args: {}, result: [] },
          action: {
            tool: RULE.action_tool,
            args: { slug: 'mon-projet', label: 'mon-projet' },
            result: { slug: 'mon-projet' },
          },
        })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<RulesTab />)

    await user.click(await screen.findByRole('button', { name: /jouer|play/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(
      within(dialog).getByLabelText(/workspace de test|test workspace/i),
      'mon-projet',
    )
    await user.click(within(dialog).getByRole('button', { name: /jouer|play/i }))

    expect(
      await within(dialog).findByText(/action exécutée|action executed/i),
    ).toBeInTheDocument()
    expect(testedBody).toEqual({ workspace: 'mon-projet' })
  })
})
