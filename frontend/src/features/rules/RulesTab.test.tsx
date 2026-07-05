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
  conditions: [
    {
      service_id: 's1',
      tool: 'docflow__list_workspaces',
      args: {},
      path: 'slug',
      operator: 'not_contains' as const,
      value: '{workspace}',
    },
  ],
  actions: [
    {
      service_id: 's1',
      tool: 'docflow__create_workspace',
      args: { slug: '{workspace}', label: '{workspace}' },
    },
  ],
  next_rule_id: null,
  created_at: '2026-07-05T00:00:00Z',
  updated_at: null,
}

const RULE2 = { ...RULE, id: 'r2', name: 'Règle chaînée', next_rule_id: 'r1' }

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('RulesTab', () => {
  it('affiche les règles : événement, résumé, enchaînement', async () => {
    server.use(
      http.get('/me/rules', () => HttpResponse.json([RULE, RULE2])),
      http.get('/me/rules/events', () => HttpResponse.json(['workspace.created'])),
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
    )
    renderWithProviders(<RulesTab />)
    expect(await screen.findByText('Créer le workspace docflow')).toBeInTheDocument()
    expect(screen.getAllByText('workspace.created').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/1 condition\(s\) · 1 action\(s\)/).length).toBe(2)
    expect(
      screen.getByText(/puis « Créer le workspace docflow »|then "Créer le workspace docflow"/),
    ).toBeInTheDocument()
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

  it('crée une règle avec deux actions (POST)', async () => {
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

    await user.click(screen.getByLabelText(/événement déclencheur|trigger event/i))
    await user.click(await screen.findByRole('option', { name: 'workspace.created' }))

    // Condition 1
    let serviceSelects = screen.getAllByLabelText(/^service$/i)
    await user.click(serviceSelects[0])
    await user.click(await screen.findByRole('option', { name: 'Docflow' }))
    let toolSelects = screen.getAllByLabelText(/méthode mcp|mcp method/i)
    await user.click(toolSelects[0])
    await user.click(await screen.findByRole('option', { name: 'docflow__list_workspaces' }))
    await user.type(screen.getByLabelText(/chemin d'extraction|extraction path/i), 'slug')
    await user.type(screen.getByLabelText(/valeur comparée|compared value/i), '{{workspace}')

    // Action 1
    await user.click(serviceSelects[1])
    await user.click(await screen.findByRole('option', { name: 'Docflow' }))
    await user.click(toolSelects[1])
    await user.click(await screen.findByRole('option', { name: 'docflow__create_workspace' }))

    // Action 2 (ajoutée)
    await user.click(screen.getByRole('button', { name: /ajouter une action|add an action/i }))
    serviceSelects = screen.getAllByLabelText(/^service$/i)
    toolSelects = screen.getAllByLabelText(/méthode mcp|mcp method/i)
    await user.click(serviceSelects[2])
    await user.click(await screen.findByRole('option', { name: 'Docflow' }))
    await user.click(toolSelects[2])
    await user.click(await screen.findByRole('option', { name: 'docflow__list_workspaces' }))

    await user.click(screen.getByRole('button', { name: /enregistrer|save/i }))

    await waitFor(() =>
      expect(posted).toEqual({
        name: 'Ma règle',
        enabled: true,
        event_type: 'workspace.created',
        conditions: [
          {
            service_id: 's1',
            tool: 'docflow__list_workspaces',
            args: {},
            path: 'slug',
            operator: 'not_contains',
            value: '{workspace}',
          },
        ],
        actions: [
          { service_id: 's1', tool: 'docflow__create_workspace', args: {} },
          { service_id: 's1', tool: 'docflow__list_workspaces', args: {} },
        ],
        next_rule_id: null,
      }),
    )
  })

  it('pré-remplit les paramètres depuis le schéma de la méthode choisie', async () => {
    const toolsWithSchema = [
      {
        name: 'docflow__workspace_exists',
        description: 'teste',
        input_schema: {
          type: 'object',
          properties: { workspace_slug: { type: 'string' } },
          required: ['workspace_slug'],
        },
      },
    ]
    server.use(
      http.get('/me/rules', () => HttpResponse.json([])),
      http.get('/me/rules/events', () => HttpResponse.json(['workspace.created'])),
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
      http.get('/me/services/s1/tools', () => HttpResponse.json(toolsWithSchema)),
    )
    const user = userEvent.setup()
    renderWithProviders(<RulesTab />)

    await user.click(await screen.findByRole('button', { name: /ajouter une règle|add a rule/i }))
    await user.click(screen.getAllByLabelText(/^service$/i)[0])
    await user.click(await screen.findByRole('option', { name: 'Docflow' }))
    await user.click(screen.getAllByLabelText(/méthode mcp|mcp method/i)[0])
    await user.click(await screen.findByRole('option', { name: 'docflow__workspace_exists' }))

    const textarea = screen.getAllByLabelText(/paramètres|parameters/i)[0] as HTMLTextAreaElement
    expect(JSON.parse(textarea.value)).toEqual({ workspace_slug: '' })
  })

  it("teste un appel MCP et affiche le retour brut", async () => {
    let posted: unknown = null
    server.use(
      http.get('/me/rules', () => HttpResponse.json([])),
      http.get('/me/rules/events', () => HttpResponse.json(['workspace.created'])),
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
      http.get('/me/services/s1/tools', () => HttpResponse.json(TOOLS)),
      http.post('/me/services/s1/tools/call', async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json({
          ok: true,
          args: { status: 'all' },
          result: [{ slug: 'demo' }],
        })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<RulesTab />)

    await user.click(await screen.findByRole('button', { name: /ajouter une règle|add a rule/i }))
    await user.type(
      screen.getByLabelText(/workspace de test|test workspace/i),
      'mon-projet',
    )
    await user.click(screen.getAllByLabelText(/^service$/i)[0])
    await user.click(await screen.findByRole('option', { name: 'Docflow' }))
    await user.click(screen.getAllByLabelText(/méthode mcp|mcp method/i)[0])
    await user.click(await screen.findByRole('option', { name: 'docflow__list_workspaces' }))

    await user.click(screen.getAllByRole('button', { name: /^(tester|test)$/i })[0])

    expect(await screen.findByText(/"slug": "demo"/)).toBeInTheDocument()
    expect(posted).toEqual({
      tool: 'docflow__list_workspaces',
      args: {},
      workspace: 'mon-projet',
    })
  })

  it('joue une règle et affiche les traces de la chaîne', async () => {
    let testedBody: unknown = null
    server.use(
      http.get('/me/rules', () => HttpResponse.json([RULE])),
      http.get('/me/rules/events', () => HttpResponse.json(['workspace.created'])),
      http.get('/me/services', () => HttpResponse.json([SERVICE])),
      http.post('/me/rules/r1/test', async ({ request }) => {
        testedBody = await request.json()
        return HttpResponse.json({
          ok: true,
          traces: [
            {
              rule: RULE.name,
              conditions: [
                { tool: 'docflow__list_workspaces', args: {}, result: [], ok: true },
              ],
              matched: true,
              actions: [
                {
                  tool: 'docflow__create_workspace',
                  args: { slug: 'mon-projet' },
                  result: { slug: 'mon-projet' },
                },
              ],
            },
            {
              rule: 'Règle chaînée',
              conditions: [],
              matched: true,
              actions: [],
            },
          ],
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
    await user.click(within(dialog).getByRole('button', { name: /^(jouer|play)$/i }))

    expect(
      (await within(dialog).findAllByText(/actions exécutées|actions executed/i)).length,
    ).toBe(2)
    expect(within(dialog).getByText('Règle chaînée')).toBeInTheDocument()
    expect(testedBody).toEqual({ workspace: 'mon-projet' })
  })
})
