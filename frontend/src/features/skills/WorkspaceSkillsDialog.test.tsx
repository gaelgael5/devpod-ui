import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import WorkspaceSkillsDialog from './WorkspaceSkillsDialog'

const PLACEMENT = {
  placement_id: 11,
  grant_id: 3,
  skill_id: 'github/awesome-copilot/git-commit',
  grant_statut: 'granted',
  approved_hash: 'sha256:aaa',
  placement_statut: 'unverified',
  installed_hash: 'sha256:bbb',
}

const GRANTED = { id: 4, skill_id: 'a/b', statut: 'granted', approved_hash: 'sha256:x' }

describe('WorkspaceSkillsDialog', () => {
  it('liste les placements avec le statut de vérification et retire', async () => {
    let deleted = false
    server.use(
      http.get('/me/workspaces/doc/skills', () => HttpResponse.json([PLACEMENT])),
      http.get('/me/skills/grants', () => HttpResponse.json([])),
      http.delete('/me/workspaces/doc/skills/11', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceSkillsDialog wsName="doc" onClose={() => {}} />)

    await waitFor(() =>
      expect(screen.getByText('github/awesome-copilot/git-commit')).toBeInTheDocument(),
    )
    expect(screen.getByText('unverified')).toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: /Remove github\/awesome-copilot\/git-commit/ }),
    )
    await waitFor(() => expect(deleted).toBe(true))
  })

  it("n'offre à l'installation que les skills granted non placées", async () => {
    let posted: unknown = null
    server.use(
      http.get('/me/workspaces/doc/skills', () => HttpResponse.json([])),
      http.get('/me/skills/grants', () =>
        HttpResponse.json([
          GRANTED,
          { id: 5, skill_id: 'c/d', statut: 'pending', approved_hash: null },
        ]),
      ),
      http.post('/me/workspaces/doc/skills', async ({ request }) => {
        posted = await request.json()
        return HttpResponse.json(
          { ...PLACEMENT, skill_id: 'a/b', placement_statut: 'verified', installed_hash: 'sha256:x' },
          { status: 201 },
        )
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceSkillsDialog wsName="doc" onClose={() => {}} />)

    const select = await screen.findByRole('combobox')
    await screen.findByRole('option', { name: 'a/b' })
    // La pending c/d n'est pas proposée.
    expect(screen.queryByRole('option', { name: 'c/d' })).not.toBeInTheDocument()
    await user.selectOptions(select, 'a/b')
    await user.click(screen.getByRole('button', { name: 'Install' }))
    await waitFor(() => expect(posted).toEqual({ skill_id: 'a/b' }))
  })
})
