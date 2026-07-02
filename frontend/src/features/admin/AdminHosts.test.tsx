import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminHosts from './AdminHosts'

vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn(function Terminal() {
    return {
      open: vi.fn(), dispose: vi.fn(),
      onData: vi.fn(() => ({ dispose: vi.fn() })),
      write: vi.fn(), loadAddon: vi.fn(), focus: vi.fn(),
    }
  }),
}))
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn(function FitAddon() {
    return { fit: vi.fn(), dispose: vi.fn() }
  }),
}))

describe('AdminHosts', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
  })

  it('affiche le titre', () => {
    renderWithProviders(<AdminHosts />)
    expect(screen.getByRole('heading', { name: /hosts|hôtes/i })).toBeInTheDocument()
  })

  it('affiche les hosts chargés', async () => {
    renderWithProviders(<AdminHosts />)
    await waitFor(() => {
      expect(screen.getByText('pve1')).toBeInTheDocument()
      expect(screen.getByText('pve2')).toBeInTheDocument()
    })
  })

  it("n'affiche pas le bouton SSH sur une ligne docker-tls", async () => {
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('pve1')).toBeInTheDocument())
    const rows = screen.getAllByRole('row')
    const pve1Row = rows.find(r => r.textContent?.includes('pve1'))
    expect(pve1Row).toBeDefined()
    expect(pve1Row!.querySelector('[data-ssh]')).toBeNull()
  })

  it('affiche le bouton SSH sur une ligne ssh et ouvre la fenêtre au clic', async () => {
    renderWithProviders(<AdminHosts />)
    await waitFor(() => expect(screen.getByText('ssh-dev')).toBeInTheDocument())
    const sshBtn = screen.getByRole('button', { name: /^SSH$/i })
    expect(sshBtn).toBeInTheDocument()
    await userEvent.click(sshBtn)
    // L'adresse apparaît deux fois : cellule du tableau + bandeau de la fenêtre SSH ouverte.
    expect(screen.getAllByText(/debian@192\.168\.10\.175/)).toHaveLength(2)
  })
})
