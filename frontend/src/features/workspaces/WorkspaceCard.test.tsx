import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import WorkspaceCard from './WorkspaceCard'
import type { WorkspaceSpec, WorkspaceStatus } from './types'

vi.mock('./SshKeyDialog', () => ({
  default: ({ open }: { open: boolean }) => open ? <div role="dialog" /> : null,
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

function card(status: WorkspaceStatus['status'], url?: string) {
  const ws: WorkspaceStatus = { ws_id: 'alice-myapp', status, url }
  return (
    <WorkspaceCard
      spec={SPEC}
      status={ws}
      onStop={vi.fn()}
      onDelete={vi.fn()}
    />
  )
}

describe('WorkspaceCard', () => {
  it('affiche le nom et la source', () => {
    renderWithProviders(card('running', 'https://alice-myapp.dev.yoops.org'))
    expect(screen.getByText('myapp')).toBeInTheDocument()
    expect(screen.getByText('github.com/org/myapp')).toBeInTheDocument()
  })

  it('affiche « injoignable » quand running mais reachable=false (bug 2846f916)', () => {
    const ws: WorkspaceStatus = {
      ws_id: 'alice-myapp', status: 'running', url: 'https://x', reachable: false,
    }
    renderWithProviders(
      <WorkspaceCard spec={SPEC} status={ws} onStop={vi.fn()} onDelete={vi.fn()} />,
    )
    expect(screen.getByText(/unreachable|injoignable/i)).toBeInTheDocument()
    expect(screen.queryByText(/^(running|en cours)$/i)).not.toBeInTheDocument()
  })

  it("affiche la suggestion d'arrêt quand stop_suggested (6016436b) et déclenche onStop", async () => {
    const onStop = vi.fn()
    const ws: WorkspaceStatus = {
      ws_id: 'alice-myapp', status: 'running', url: 'https://x',
      stop_suggested: true, idle_since: new Date(Date.now() - 3 * 3600_000).toISOString(),
    }
    renderWithProviders(
      <WorkspaceCard spec={SPEC} status={ws} onStop={onStop} onDelete={vi.fn()} />,
    )
    const banner = screen.getByTestId('idle-suggestion')
    expect(banner).toHaveTextContent(/inactif|idle/i)
    expect(banner).toHaveTextContent(/3 h/)
    // L'honnêteté du coût : l'arrêt détruit le tmux.
    expect(banner).toHaveTextContent(/tmux/i)
    const user = userEvent.setup()
    await user.click(screen.getAllByRole('button', { name: /stop|arrêter/i })[0])
    expect(onStop).toHaveBeenCalledWith('myapp')
  })

  it("masque la suggestion d'arrêt quand le workspace est épinglé « garder actif »", () => {
    const ws: WorkspaceStatus = {
      ws_id: 'alice-myapp', status: 'running', url: 'https://x',
      stop_suggested: true, keep_active: true,
      idle_since: new Date(Date.now() - 3 * 3600_000).toISOString(),
    }
    renderWithProviders(
      <WorkspaceCard spec={SPEC} status={ws} onStop={vi.fn()} onDelete={vi.fn()} />,
    )
    expect(screen.queryByTestId('idle-suggestion')).not.toBeInTheDocument()
  })

  it("n'affiche pas de suggestion sans stop_suggested", () => {
    renderWithProviders(card('running', 'https://x'))
    expect(screen.queryByTestId('idle-suggestion')).not.toBeInTheDocument()
  })

  it('affiche le badge "running" et le bouton Ouvrir', () => {
    renderWithProviders(card('running', 'https://alice-myapp.dev.yoops.org'))
    expect(screen.getByText(/running|en cours/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open|ouvrir/i })).toBeInTheDocument()
  })

  it('affiche Stop quand running', () => {
    renderWithProviders(card('running', 'https://alice-myapp.dev.yoops.org'))
    expect(screen.getByRole('button', { name: /stop|arrêter/i })).toBeInTheDocument()
  })

  it('affiche Démarrer et Supprimer quand stopped', () => {
    renderWithProviders(card('stopped'))
    expect(screen.getByRole('button', { name: /start|démarrer/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delete|supprimer/i })).toBeInTheDocument()
  })

  it('désactive les actions quand provisioning', () => {
    renderWithProviders(card('provisioning'))
    expect(screen.queryByRole('button', { name: /stop|arrêter/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /open|ouvrir/i })).not.toBeInTheDocument()
  })

  it('appelle onStop au clic Stop', async () => {
    const user = userEvent.setup()
    const onStop = vi.fn()
    const ws: WorkspaceStatus = { ws_id: 'alice-myapp', status: 'running', url: 'https://x' }
    renderWithProviders(
      <WorkspaceCard spec={SPEC} status={ws} onStop={onStop} onDelete={vi.fn()} />
    )
    await user.click(screen.getByRole('button', { name: /stop|arrêter/i }))
    expect(onStop).toHaveBeenCalledWith('myapp')
  })

  it('propose Clé SSH dans le menu Actions quand spec.ssh_key=true', async () => {
    Element.prototype.hasPointerCapture = vi.fn()
    Element.prototype.scrollIntoView = vi.fn()
    const user = userEvent.setup()
    const spec: WorkspaceSpec = { ...SPEC, ssh_key: true }
    renderWithProviders(
      <WorkspaceCard
        spec={spec}
        status={{ ws_id: 'alice-myapp', status: 'running', url: 'https://x' }}
        onStop={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    await user.click(screen.getByRole('button', { name: /^actions$/i }))
    expect(await screen.findByRole('menuitem', { name: /clé ssh|ssh key/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /shell ssh|ssh shell/i })).toBeInTheDocument()
  })

  it("ne propose pas Clé SSH quand spec.ssh_key=false", async () => {
    Element.prototype.hasPointerCapture = vi.fn()
    Element.prototype.scrollIntoView = vi.fn()
    const user = userEvent.setup()
    const spec: WorkspaceSpec = { ...SPEC, ssh_key: false }
    renderWithProviders(
      <WorkspaceCard
        spec={spec}
        status={{ ws_id: 'alice-myapp', status: 'running', url: 'https://x' }}
        onStop={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    await user.click(screen.getByRole('button', { name: /^actions$/i }))
    expect(await screen.findByRole('menuitem', { name: /add vm for test/i })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: /clé ssh|ssh key/i })).not.toBeInTheDocument()
  })

  it("ouvre le dialog SSH via l'item Clé SSH du menu Actions", async () => {
    Element.prototype.hasPointerCapture = vi.fn()
    Element.prototype.scrollIntoView = vi.fn()
    const user = userEvent.setup()
    const spec: WorkspaceSpec = { ...SPEC, ssh_key: true }
    renderWithProviders(
      <WorkspaceCard
        spec={spec}
        status={{ ws_id: 'alice-myapp', status: 'running', url: 'https://x' }}
        onStop={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    await user.click(screen.getByRole('button', { name: /^actions$/i }))
    await user.click(await screen.findByRole('menuitem', { name: /clé ssh|ssh key/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('regroupe Initialize et Add VM for Test dans le menu Actions quand running', async () => {
    Element.prototype.hasPointerCapture = vi.fn()
    Element.prototype.scrollIntoView = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(card('running', 'https://alice-myapp.dev.yoops.org'))

    expect(screen.queryByRole('button', { name: /add vm for test/i })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^actions$/i }))
    expect(await screen.findByRole('menuitem', { name: /add vm for test/i })).toBeInTheDocument()
  })
})
