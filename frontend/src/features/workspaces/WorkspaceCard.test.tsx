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

  it('affiche le bouton Clé SSH quand spec.ssh_key=true', () => {
    const spec: WorkspaceSpec = { ...SPEC, ssh_key: true }
    renderWithProviders(
      <WorkspaceCard
        spec={spec}
        status={{ ws_id: 'alice-myapp', status: 'running', url: 'https://x' }}
        onStop={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: /clé ssh|ssh key/i })).toBeInTheDocument()
  })

  it("n'affiche pas le bouton Clé SSH quand spec.ssh_key=false", () => {
    const spec: WorkspaceSpec = { ...SPEC, ssh_key: false }
    renderWithProviders(
      <WorkspaceCard
        spec={spec}
        status={{ ws_id: 'alice-myapp', status: 'running', url: 'https://x' }}
        onStop={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: /clé ssh|ssh key/i })).not.toBeInTheDocument()
  })

  it('ouvre le dialog SSH au clic sur le bouton Clé SSH', async () => {
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
    await user.click(screen.getByRole('button', { name: /clé ssh|ssh key/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
