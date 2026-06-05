import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import WorkspaceCard from './WorkspaceCard'
import type { WorkspaceSpec, WorkspaceStatus } from './types'

const SPEC: WorkspaceSpec = {
  name: 'myapp',
  source: 'github.com/org/myapp',
  host: '',
  recipes: ['claude-code'],
  env: {},
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
})
