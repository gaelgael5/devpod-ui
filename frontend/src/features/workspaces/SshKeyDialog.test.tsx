import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import SshKeyDialog from './SshKeyDialog'

vi.mock('./useWorkspaceSshKey', () => ({
  useWorkspaceSshKey: (_name: string, enabled: boolean) => ({
    data: enabled ? { public_key: 'ssh-ed25519 AAAAB3NzaC1lZDI1NTE5 devpod:alice/myapp' } : undefined,
    isLoading: false,
    isError: false,
  }),
}))

describe('SshKeyDialog', () => {
  it('affiche la clé publique quand open=true', () => {
    renderWithProviders(
      <SshKeyDialog workspaceName="myapp" open={true} onOpenChange={vi.fn()} />
    )
    expect(screen.getByDisplayValue(/ssh-ed25519/)).toBeInTheDocument()
  })

  it('affiche le bouton Copier', () => {
    renderWithProviders(
      <SshKeyDialog workspaceName="myapp" open={true} onOpenChange={vi.fn()} />
    )
    expect(screen.getByRole('button', { name: /copier|copy/i })).toBeInTheDocument()
  })

  it("n'affiche pas la clé quand open=false", () => {
    renderWithProviders(
      <SshKeyDialog workspaceName="myapp" open={false} onOpenChange={vi.fn()} />
    )
    expect(screen.queryByDisplayValue(/ssh-ed25519/)).not.toBeInTheDocument()
  })
})
