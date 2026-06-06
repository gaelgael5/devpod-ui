import { screen } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminGuard from './AdminGuard'

function AdminPage() {
  return <div>admin content</div>
}

describe('AdminGuard', () => {
  beforeEach(() => useUserStore.setState({ user: null }))

  it('affiche le contenu si admin', () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev', 'admin'] } })
    renderWithProviders(
      <AdminGuard>
        <AdminPage />
      </AdminGuard>
    )
    expect(screen.getByText('admin content')).toBeInTheDocument()
  })

  it('affiche 403 si non admin', () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
    renderWithProviders(
      <AdminGuard>
        <AdminPage />
      </AdminGuard>
    )
    expect(screen.queryByText('admin content')).not.toBeInTheDocument()
    expect(screen.getByText(/access denied|accès refusé/i)).toBeInTheDocument()
  })

  it('affiche 403 si user est null', () => {
    renderWithProviders(
      <AdminGuard>
        <AdminPage />
      </AdminGuard>
    )
    expect(screen.queryByText('admin content')).not.toBeInTheDocument()
  })
})
