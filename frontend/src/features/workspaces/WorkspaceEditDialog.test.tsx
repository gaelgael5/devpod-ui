/**
 * Édition de la config d'un workspace existant.
 *
 * Le point sensible : certains champs n'entrent que dans le devcontainer.json et
 * n'ont AUCUN effet tant que l'image n'est pas reconstruite. L'utilisateur doit
 * en être averti — sans quoi il croit sa recette installée alors qu'elle n'est
 * nulle part. C'est le serveur qui tranche (`requires_recreate`), l'UI ne
 * re-devine pas la règle.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import WorkspaceEditDialog from './WorkspaceEditDialog'
import type { WorkspaceSpec } from './types'
import { useUserStore } from '@/store/user'

const patchMock = vi.fn()

// Un nœud de chaque usage : seuls ceux dédiés aux workspaces doivent être proposés.
const HOSTS = [
  { name: 'node-ws-1', type: 'ssh', usage: 'workspaces', default: true },
  { name: 'node-ws-2', type: 'ssh' },                      // usage absent ⇒ workspaces
  { name: 'vm-test-42', type: 'ssh', usage: 'tests' },
  { name: 'srv-ressources', type: 'ssh', usage: 'ressources' },
  { name: 'divers', type: 'ssh', usage: 'autres' },
  { name: 'portail', type: 'ssh', usage: 'portail' },
]

vi.mock('@/shared/api/client', () => ({
  apiFetchJson: vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'PATCH') return patchMock(url, init)
    if (url.includes('/admin/hosts')) return HOSTS
    return []
  }),
  apiFetchVoid: vi.fn(async () => undefined),
  apiFetch: vi.fn(async () => new Response('{}')),
}))

const SPEC: WorkspaceSpec = {
  name: 'myapp',
  source: 'github.com/org/myapp',
  branch: 'main',
  git_credential: '',
  host: '',
  recipes: ['python'],
  env: {},
  extra_sources: [],
}

function dialog(onRecreate?: (n: string) => void) {
  return (
    <WorkspaceEditDialog
      spec={SPEC}
      open
      onOpenChange={vi.fn()}
      onRecreate={onRecreate}
    />
  )
}

beforeEach(() => {
  patchMock.mockReset()
})

describe('WorkspaceEditDialog', () => {
  it('pré-remplit les champs avec la config actuelle', () => {
    renderWithProviders(dialog())
    expect(screen.getByLabelText(/branch/i)).toHaveValue('main')
  })

  it('envoie un PATCH sur le workspace édité', async () => {
    patchMock.mockResolvedValue({
      spec: SPEC, requires_recreate: [], requires_restart: [], added_recipes: [],
    })
    const user = userEvent.setup()
    renderWithProviders(dialog())

    await user.clear(screen.getByLabelText(/branch/i))
    await user.type(screen.getByLabelText(/branch/i), 'feature/x')
    await user.click(screen.getByRole('button', { name: /enregistrer|save/i }))

    await waitFor(() => expect(patchMock).toHaveBeenCalled())
    const [url, init] = patchMock.mock.calls[0]
    expect(url).toContain('/me/workspaces/myapp')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body).branch).toBe('feature/x')
  })

  it('avertit quand la modification exige une recréation', async () => {
    patchMock.mockResolvedValue({
      spec: SPEC,
      requires_recreate: ['recipes'],
      requires_restart: [],
      added_recipes: ['claude-code'],
    })
    const user = userEvent.setup()
    renderWithProviders(dialog())

    await user.click(screen.getByRole('button', { name: /enregistrer|save/i }))

    const warning = await screen.findByTestId('edit-recreate-warning')
    expect(warning).toHaveTextContent('recipes')
  })

  it('ne recrée jamais tout seul : le bouton doit être cliqué', async () => {
    const onRecreate = vi.fn()
    patchMock.mockResolvedValue({
      spec: SPEC,
      requires_recreate: ['recipes'],
      requires_restart: [],
      added_recipes: ['claude-code'],
    })
    const user = userEvent.setup()
    renderWithProviders(dialog(onRecreate))

    await user.click(screen.getByRole('button', { name: /enregistrer|save/i }))
    await screen.findByTestId('edit-recreate-warning')
    // Enregistrer ne déclenche AUCUNE recréation : elle détruit le travail non commité.
    expect(onRecreate).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /recréer|recreate/i }))
    expect(onRecreate).toHaveBeenCalledWith('myapp')
  })

  it('sans impact, aucun avertissement n’est affiché', async () => {
    patchMock.mockResolvedValue({
      spec: SPEC, requires_recreate: [], requires_restart: ['branch'], added_recipes: [],
    })
    const user = userEvent.setup()
    renderWithProviders(dialog())

    await user.click(screen.getByRole('button', { name: /enregistrer|save/i }))

    await waitFor(() => expect(patchMock).toHaveBeenCalled())
    expect(screen.queryByTestId('edit-recreate-warning')).not.toBeInTheDocument()
  })
})

describe('WorkspaceEditDialog — sélecteur de nœud', () => {
  function asAdmin(isAdmin: boolean) {
    useUserStore.setState({
      user: { login: 'alice', roles: [], is_admin: isAdmin },
    } as never)
  }

  it('ne propose que les nœuds dédiés aux workspaces', async () => {
    asAdmin(true)
    renderWithProviders(dialog())

    const select = await screen.findByLabelText(/nœud|node/i)
    const options = [...select.querySelectorAll('option')].map((o) => o.textContent?.trim())

    expect(options.join(' ')).toContain('node-ws-1')
    expect(options.join(' ')).toContain('node-ws-2') // usage absent ⇒ workspaces
    // Ni tests, ni ressources, ni autres, ni portail.
    expect(options.join(' ')).not.toContain('vm-test-42')
    expect(options.join(' ')).not.toContain('srv-ressources')
    expect(options.join(' ')).not.toContain('divers')
    expect(options.join(' ')).not.toContain('portail')
  })

  it('est masqué pour un non-admin (/admin/hosts lui est interdit)', async () => {
    asAdmin(false)
    renderWithProviders(dialog())

    await screen.findByLabelText(/branch/i) // le dialogue est bien rendu
    expect(screen.queryByLabelText(/nœud|node/i)).not.toBeInTheDocument()
  })

  it('conserve le nœud courant même s’il n’est plus éligible', async () => {
    asAdmin(true)
    const onDeprecatedHost = { ...SPEC, host: 'srv-ressources' }
    renderWithProviders(
      <WorkspaceEditDialog
        spec={onDeprecatedHost}
        open
        onOpenChange={vi.fn()}
      />,
    )

    const select = await screen.findByLabelText(/nœud|node/i)
    // Sans ça, le select retomberait sur « — » et enregistrer déplacerait
    // le workspace en silence.
    expect(select).toHaveValue('srv-ressources')
  })
})
