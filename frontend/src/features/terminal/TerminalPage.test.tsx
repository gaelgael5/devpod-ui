import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import i18n from '@/i18n'
import TerminalPage from './TerminalPage'

// Stub du terminal : évite xterm/WebSocket et expose wsPath + resize.
vi.mock('./FullscreenTerminal', () => ({
  default: ({ wsPath, resize }: { wsPath: string; resize: boolean }) => (
    <div data-testid="term" data-ws={wsPath} data-resize={String(resize)} />
  ),
}))

function renderAt(path: string) {
  const router = createMemoryRouter(
    [{ path: '/terminal', element: <I18nextProvider i18n={i18n}><TerminalPage /></I18nextProvider> }],
    { initialEntries: [path] },
  )
  return render(<RouterProvider router={router} />)
}

describe('TerminalPage', () => {
  it('rend le terminal host (resize activé — tmux derrière un PTY)', () => {
    renderAt('/terminal?ws=%2Fadmin%2Fhosts%2Fh1%2Fssh&title=h1')
    const term = screen.getByTestId('term')
    expect(term).toHaveAttribute('data-ws', '/admin/hosts/h1/ssh')
    expect(term).toHaveAttribute('data-resize', 'true')
  })

  it('rend le terminal workspace (resize activé)', () => {
    renderAt('/terminal?ws=%2Fme%2Fworkspaces%2Fws1%2Fssh%3Fsession%3Dmain')
    const term = screen.getByTestId('term')
    expect(term).toHaveAttribute('data-ws', '/me/workspaces/ws1/ssh?session=main')
    expect(term).toHaveAttribute('data-resize', 'true')
  })

  it('rejette une cible non autorisée (hors /me et /admin)', () => {
    renderAt('/terminal?ws=%2F%2Fevil.com%2Fssh')
    expect(screen.queryByTestId('term')).not.toBeInTheDocument()
    expect(screen.getByText(/invalide|invalid/i)).toBeInTheDocument()
  })

  it('rejette un ws absent', () => {
    renderAt('/terminal')
    expect(screen.queryByTestId('term')).not.toBeInTheDocument()
    expect(screen.getByText(/invalide|invalid/i)).toBeInTheDocument()
  })
})
