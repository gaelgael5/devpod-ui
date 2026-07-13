import { describe, it, expect } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import ComposeGallery from '../ComposeGallery'

describe('ComposeGallery route stub', () => {
  it('renders the gallery container', () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'], is_admin: false } })
    const { getByTestId } = renderWithProviders(<ComposeGallery />, { route: '/compose' })
    expect(getByTestId('compose-gallery')).toBeInTheDocument()
  })
})
