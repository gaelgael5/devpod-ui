import { describe, it, expect } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminCompose from '../AdminCompose'

describe('AdminCompose', () => {
  it('lists templates for an admin', async () => {
    useUserStore.setState({ user: { login: 'root', roles: ['admin'] } })
    const { findByText } = renderWithProviders(<AdminCompose />, { route: '/admin/compose' })
    expect(await findByText('Browserless')).toBeInTheDocument()
  })
})
