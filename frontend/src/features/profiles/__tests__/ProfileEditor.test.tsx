import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import ProfileEditor from '../ProfileEditor'

describe('ProfileEditor — création', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
  })

  it('affiche les champs name et description vides', () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/new' })
    const nameInput = screen.getByLabelText(/nom|name/i)
    const descInput = screen.getByLabelText(/description/i)
    expect(nameInput).toHaveValue('')
    expect(descInput).toHaveValue('')
  })

  it('affiche la preview devcontainer vide initialement', () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/new' })
    const pre = screen.getByRole('code')
    expect(pre).toHaveTextContent('"extensions": []')
  })

  it('le bouton Enregistrer est désactivé si le nom est vide', () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/new' })
    const saveBtn = screen.getByRole('button', { name: /enregistrer|save/i })
    expect(saveBtn).toBeDisabled()
  })

  it('active le bouton Enregistrer quand le nom est renseigné', async () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/new' })
    const nameInput = screen.getByLabelText(/nom|name/i)
    await userEvent.type(nameInput, 'Mon profil')
    const saveBtn = screen.getByRole('button', { name: /enregistrer|save/i })
    expect(saveBtn).not.toBeDisabled()
  })
})

describe('ProfileEditor — édition', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
  })

  it('préremplie le nom et la description depuis le profil existant', async () => {
    renderWithProviders(<ProfileEditor />, { route: '/profiles/frontend-react' })
    expect(await screen.findByDisplayValue('Frontend React')).toBeInTheDocument()
  })
})
