/**
 * Le menu admin regroupe ses entrees : quatre pages tournent autour des
 * evenements, quatre decrivent le parc de machines. Ce qui compte ici est que
 * ces entrees ne trainent plus a la racine du menu — elles ne s'atteignent que
 * par leur sous-menu.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AppShell from './AppShell'

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

async function ouvrirMenuAdmin() {
  useUserStore.setState({
    user: { login: 'alice', roles: ['dev', 'admin'], is_admin: true },
  })
  renderWithProviders(<AppShell />)
  // Le declencheur est la pastille d'initiales (les majuscules viennent du CSS).
  await userEvent.click(screen.getByText('al'))
}

describe('AppShell — menu admin', () => {
  beforeEach(() => useUserStore.setState({ user: null }))

  it('propose les sous-menus Gestion, Evenements et Machines', async () => {
    await ouvrirMenuAdmin()

    expect(screen.getByText(/^gestion$|^manage$/i)).toBeInTheDocument()
    expect(screen.getByText(/événements|^events$/i)).toBeInTheDocument()
    expect(screen.getByText(/^machines$/i)).toBeInTheDocument()
  })

  it('ne laisse plus ces entrees a la racine du menu', async () => {
    await ouvrirMenuAdmin()

    // Repliees dans leur sous-menu, elles ne sont pas rendues tant qu'il n'est
    // pas ouvert.
    expect(screen.queryByText(/types d.hyperviseurs|hypervisor types/i)).toBeNull()
    expect(screen.queryByText(/hôtes docker|docker hosts/i)).toBeNull()
    expect(screen.queryByText(/journal des .v.nements|event journal/i)).toBeNull()
    expect(screen.queryByText(/^r.seau$|^network$/i)).toBeNull()
    expect(screen.queryByText(/oidc/i)).toBeNull()
    // Les entrees restees a la racine, elles, sont bien la.
    expect(screen.getByText(/utilisateurs|users/i)).toBeInTheDocument()
  })
})


describe('AppShell — acces aux forfaits', () => {
  beforeEach(() => useUserStore.setState({ user: null }))

  async function ouvrirMenu(admin: boolean) {
    useUserStore.setState({
      user: { login: 'alice', roles: admin ? ['dev', 'admin'] : ['dev'], is_admin: admin },
    })
    renderWithProviders(<AppShell />)
    await userEvent.click(screen.getByText('al'))
  }

  it('propose les forfaits a un utilisateur SANS role admin', async () => {
    // Consulter ce qui est propose regarde tout abonne : l'entree vit hors du
    // bloc reserve a l'administration, et c'est tout l'objet de ce test.
    await ouvrirMenu(false)

    expect(screen.getByText(/nos forfaits|our plans/i)).toBeInTheDocument()
  })

  it("ne montre a un non-admin aucune entree d'administration", async () => {
    await ouvrirMenu(false)

    expect(screen.queryByText(/^gestion$|^manage$/i)).toBeNull()
    expect(screen.queryByText(/^machines$/i)).toBeNull()
    expect(screen.queryByText(/utilisateurs|users/i)).toBeNull()
  })

  it('la propose aussi a un administrateur', async () => {
    await ouvrirMenu(true)

    expect(screen.getByText(/nos forfaits|our plans/i)).toBeInTheDocument()
  })
})
