import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import { ws } from 'msw'
import type { WebSocketClientConnectionProtocol } from '@mswjs/interceptors/WebSocket'
import i18n from '@/i18n'
import { server } from '@/test/server'
import SshTerminalWindow from './SshTerminalWindow'
import type { HostConfig } from './useHosts'

// ── Mocks xterm ───────────────────────────────────────────────────────────────
// vi.hoisted ensures these are evaluated before the vi.mock factory hoisting.
const { mockTerminalInstance } = vi.hoisted(() => {
  const mockTerminalInstance = {
    open: vi.fn(),
    dispose: vi.fn(),
    onData: vi.fn(() => ({ dispose: vi.fn() })),
    write: vi.fn(),
    loadAddon: vi.fn(),
    focus: vi.fn(),
  }
  return { mockTerminalInstance }
})

vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn(function Terminal() {
    return mockTerminalInstance
  }),
}))
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn(function FitAddon() {
    return { fit: vi.fn(), dispose: vi.fn() }
  }),
}))

// ── MSW WebSocket handler ────────────────────────────────────────────────────
// MSW intercepts WebSocket connections at network level. We create a link and
// register a connection handler to capture the client reference for assertions.
const sshWsLink = ws.link('ws://localhost:3000/admin/hosts/:name/ssh')

let wsClient: WebSocketClientConnectionProtocol | null = null
let wsCloseCalled = false

// ── Helpers ───────────────────────────────────────────────────────────────────
const SSH_HOST: HostConfig = {
  name: 'ssh-dev',
  type: 'ssh',
  address: 'debian@192.168.10.175',
  key_path: '/data/keys/hosts/ssh_dev_ed25519',
}

function renderWindow(onClose = vi.fn()) {
  return render(
    <I18nextProvider i18n={i18n}>
      <SshTerminalWindow host={SSH_HOST} onClose={onClose} />
    </I18nextProvider>
  )
}

// ── Tests ─────────────────────────────────────────────────────────────────────
describe('SshTerminalWindow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    wsClient = null
    wsCloseCalled = false
    // Register WS handler for the SSH endpoint
    const handler = sshWsLink.addEventListener('connection', ({ client }) => {
      wsClient = client
      client.addEventListener('close', () => {
        wsCloseCalled = true
      })
    })
    server.use(handler)
  })

  it("affiche l'adresse SSH dans le header", () => {
    renderWindow()
    expect(screen.getByText(/debian@192\.168\.10\.175/)).toBeInTheDocument()
  })

  it('se connecte au bon endpoint WebSocket', async () => {
    renderWindow()
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80))
    })
    // wsClient non-null signifie que l'URL ws://localhost:3000/admin/hosts/ssh-dev/ssh a matché
    expect(wsClient).not.toBeNull()
  })

  it('appelle onClose et ferme le WebSocket au clic sur le bouton rouge', async () => {
    const onClose = vi.fn()
    renderWindow(onClose)
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80))
    })
    const btn = screen.getByRole('button', { name: /fermer|close/i })
    await userEvent.click(btn)
    expect(onClose).toHaveBeenCalledOnce()
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20))
    })
    expect(wsCloseCalled).toBe(true)
  })

  it("écrit dans le terminal à la réception d'un message WebSocket", async () => {
    renderWindow()
    // Allow the WS connection to establish via MSW interceptor
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80))
    })
    // Send a message from "server" to the client
    act(() => {
      if (wsClient) {
        wsClient.send(new ArrayBuffer(4))
      }
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20))
    })
    expect(mockTerminalInstance.write).toHaveBeenCalled()
  })

  it('dispose le terminal au démontage', async () => {
    const { unmount } = renderWindow()
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80))
    })
    act(() => {
      unmount()
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20))
    })
    expect(mockTerminalInstance.dispose).toHaveBeenCalled()
    expect(wsCloseCalled).toBe(true)
  })
})
