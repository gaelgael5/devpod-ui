import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import SkillsTab from './SkillsTab'

const RESULT = {
  id: 'github/awesome-copilot/git-commit',
  skillId: 'git-commit',
  name: 'git-commit',
  installs: 38883,
  source: 'github/awesome-copilot',
}

function stubBase(grants: unknown[] = []) {
  server.use(
    http.get('/me/secrets', () => HttpResponse.json([])),
    http.get('/me/skills/grants', () => HttpResponse.json(grants)),
    http.get('/me/skills/audit', () =>
      HttpResponse.json({ 'git-commit': { socket: { risk: 'safe' } } }),
    ),
  )
}

describe('SkillsTab', () => {
  it('recherche et affiche les résultats avec le risque agrégé', async () => {
    let searchUrl = ''
    stubBase()
    server.use(
      http.get('/me/skills/search', ({ request }) => {
        searchUrl = request.url
        return HttpResponse.json({ query: 'git', searchType: 'fuzzy', skills: [RESULT] })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<SkillsTab />)

    await user.type(screen.getByPlaceholderText('Search a skill…'), 'git')
    await user.click(screen.getByRole('button', { name: /Search/ }))

    await waitFor(() => expect(screen.getByText('git-commit')).toBeInTheDocument())
    expect(searchUrl).toContain('q=git')
    expect(searchUrl).toContain('search_type=fuzzy')
    await waitFor(() => expect(screen.getByText('safe')).toBeInTheDocument())
  })

  it('« Add » crée une demande de grant pending', async () => {
    let posted: unknown = null
    stubBase()
    server.use(
      http.get('/me/skills/search', () =>
        HttpResponse.json({ query: 'git', searchType: 'fuzzy', skills: [RESULT] }),
      ),
      http.post('/me/skills/grants', async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json(
          { id: 1, skill_id: RESULT.id, statut: 'pending', created: true },
          { status: 201 },
        )
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<SkillsTab />)

    await user.type(screen.getByPlaceholderText('Search a skill…'), 'git')
    await user.click(screen.getByRole('button', { name: /Search/ }))
    await waitFor(() => expect(screen.getByText('git-commit')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(posted).toEqual({ skill_id: RESULT.id }))
  })

  it('affiche le statut du grant à la place du bouton Add', async () => {
    stubBase([{ id: 1, skill_id: RESULT.id, statut: 'pending' }])
    server.use(
      http.get('/me/skills/search', () =>
        HttpResponse.json({ query: 'git', searchType: 'fuzzy', skills: [RESULT] }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<SkillsTab />)

    await user.type(screen.getByPlaceholderText('Search a skill…'), 'git')
    await user.click(screen.getByRole('button', { name: /Search/ }))

    // Le badge apparaît sur le résultat ET dans le panneau Validations intégré.
    await waitFor(() =>
      expect(screen.getAllByText('Pending validation').length).toBeGreaterThan(0),
    )
    expect(screen.queryByRole('button', { name: 'Add' })).not.toBeInTheDocument()
  })
})
