import { describe, it, expect } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import ComposeGallery from '../ComposeGallery'

describe('ComposeGallery', () => {
  it('lists templates from the API', async () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
    const { findByText } = renderWithProviders(<ComposeGallery />, { route: '/compose' })
    expect(await findByText('Browserless')).toBeInTheDocument()
  })
})
