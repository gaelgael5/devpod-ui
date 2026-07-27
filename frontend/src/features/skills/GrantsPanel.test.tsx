import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import GrantsPanel from './GrantsPanel'

const BASE_GRANT = {
  id: 7,
  user_subject: 'sub-alice',
  skill_id: 'github/awesome-copilot/git-commit',
  approved_hash: null,
  statut: 'pending',
}

describe('GrantsPanel', () => {
  it('valide une demande pending (hash figé côté serveur)', async () => {
    let approved = false
    server.use(
      http.get('/me/skills/grants', () => HttpResponse.json([BASE_GRANT])),
      http.post('/me/skills/grants/7/approve', () => {
        approved = true
        return HttpResponse.json({ ...BASE_GRANT, statut: 'granted', approved_hash: 'sha256:x' })
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<GrantsPanel />)

    await waitFor(() =>
      expect(screen.getByText('github/awesome-copilot/git-commit')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(approved).toBe(true))
  })

  it('signale une re-validation après dérive de hash et compare les hashes', async () => {
    server.use(
      http.get('/me/skills/grants', () =>
        HttpResponse.json([{ ...BASE_GRANT, approved_hash: 'sha256:old' }]),
      ),
      http.get('/me/skills/grants/7/skillmd', () =>
        HttpResponse.json({
          content: '# skill',
          hash: 'sha256:new',
          approved_hash: 'sha256:old',
        }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<GrantsPanel />)

    await waitFor(() =>
      expect(screen.getByText('Re-validation (hash drifted)')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Review' }))
    await waitFor(() => expect(screen.getByText(/sha256:new/)).toBeInTheDocument())
    expect(screen.getByText(/content changed since validation/)).toBeInTheDocument()
  })

  it('granted → Pause + Revoke ; paused → Resume ; revoked → aucune action', async () => {
    server.use(
      http.get('/me/skills/grants', () =>
        HttpResponse.json([
          { ...BASE_GRANT, id: 1, statut: 'granted' },
          { ...BASE_GRANT, id: 2, skill_id: 'a/b', statut: 'paused' },
          { ...BASE_GRANT, id: 3, skill_id: 'c/d', statut: 'revoked' },
        ]),
      ),
    )
    renderWithProviders(<GrantsPanel />)

    await waitFor(() => expect(screen.getByText('a/b')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument()
    // 2 boutons Revoke (granted + paused), aucun pour le révoqué.
    expect(screen.getAllByRole('button', { name: 'Revoke' })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })
})
