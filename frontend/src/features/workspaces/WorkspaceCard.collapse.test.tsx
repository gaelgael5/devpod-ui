/**
 * Repli d'une carte workspace, persisté par utilisateur.
 *
 * Fichier séparé de WorkspaceCard.test.tsx : on y mocke le client API pour que
 * la mutation de préférence RÉUSSISSE. Sans ça, `useSetPreference` applique sa
 * mise à jour optimiste puis la ROLLBACK à l'échec du PUT (pas de serveur en
 * test) — le repli semblerait non réversible alors que c'est le filet d'erreur
 * qui joue son rôle. Mocker ici seulement évite d'altérer les 14 tests voisins.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import WorkspaceCard from './WorkspaceCard'
import type { WorkspaceSpec, WorkspaceStatus } from './types'

// Les préférences sont une map ; les autres endpoints de la carte (machines de
// test, déploiements, sessions…) renvoient des listes — un `{}` global ferait
// planter `hosts.map`. On distingue donc sur l'URL.
vi.mock('@/shared/api/client', () => ({
  apiFetchJson: vi.fn(async (url: string) =>
    url.includes('/preferences') ? {} : [],
  ),
  apiFetchVoid: vi.fn(async () => undefined),
  apiFetch: vi.fn(async () => new Response('{}')),
}))

vi.mock('./SshKeyDialog', () => ({
  default: ({ open }: { open: boolean }) => (open ? <div role="dialog" /> : null),
}))

const SPEC: WorkspaceSpec = {
  name: 'myapp',
  source: 'github.com/org/myapp',
  branch: '',
  git_credential: '',
  host: '',
  recipes: ['claude-code'],
  env: {},
  extra_sources: [],
}

function card() {
  const ws: WorkspaceStatus = { ws_id: 'alice-myapp', status: 'running' }
  return <WorkspaceCard spec={SPEC} status={ws} onStop={vi.fn()} onDelete={vi.fn()} />
}

describe('WorkspaceCard — repli', () => {
  it('déplié par défaut : rien n’est masqué sans préférence enregistrée', () => {
    renderWithProviders(card())
    expect(screen.getByText('claude-code')).toBeInTheDocument()
    expect(screen.getByTestId('workspace-collapse-myapp')).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('replié : recettes masquées, mais nom/source restent lisibles', async () => {
    const user = userEvent.setup()
    renderWithProviders(card())

    await user.click(screen.getByTestId('workspace-collapse-myapp'))

    expect(screen.queryByText('claude-code')).not.toBeInTheDocument()
    // La carte doit rester identifiable et pilotable sans la déplier.
    expect(screen.getByText('myapp')).toBeInTheDocument()
    expect(screen.getByText('github.com/org/myapp')).toBeInTheDocument()
  })

  it('le repli est réversible', async () => {
    const user = userEvent.setup()
    renderWithProviders(card())
    const toggle = screen.getByTestId('workspace-collapse-myapp')

    await user.click(toggle)
    expect(screen.queryByText('claude-code')).not.toBeInTheDocument()

    await user.click(toggle)
    expect(screen.getByText('claude-code')).toBeInTheDocument()
  })

  it('aria-expanded suit l’état (lecteurs d’écran)', async () => {
    const user = userEvent.setup()
    renderWithProviders(card())
    const toggle = screen.getByTestId('workspace-collapse-myapp')

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('persiste sous une clé propre au workspace', async () => {
    const { apiFetchVoid } = await import('@/shared/api/client')
    const user = userEvent.setup()
    renderWithProviders(card())

    await user.click(screen.getByTestId('workspace-collapse-myapp'))

    // Clé par workspace : replier `myapp` ne doit pas replier les autres cartes.
    expect(apiFetchVoid).toHaveBeenCalledWith(
      expect.stringContaining('workspaces.card.myapp.collapse'),
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ bool: true }) }),
    )
  })
})
