/**
 * Barre de liens entre ecrans voisins.
 *
 * Ce qu'elle evite : sur mobile, atteindre l'ecran jumeau demandait d'ouvrir le
 * menu profil, un sous-menu, puis de viser. Ce que ces tests verrouillent :
 * elle propose bien TOUS les voisins du groupe, elle designe l'ecran courant, et
 * elle se tait la ou il n'y a pas de groupe.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import i18n from '@/i18n'
import SectionNav from './SectionNav'
import { SECTION_FORFAITS, SECTION_MACHINES, sectionDe } from './sections'

function renderA(route: string) {
  const router = createMemoryRouter(
    [{ path: '*', element: <I18nextProvider i18n={i18n}><SectionNav /></I18nextProvider> }],
    { initialEntries: [route] },
  )
  return render(<RouterProvider router={router} />)
}

describe('SectionNav', () => {
  it('propose les trois ecrans du groupe Forfaits', () => {
    renderA('/admin/billing-catalog')

    for (const lien of SECTION_FORFAITS.liens) {
      expect(screen.getByRole('link', { name: i18n.t(lien.labelKey) })).toHaveAttribute(
        'href',
        lien.path,
      )
    }
  })

  it('propose les quatre ecrans du groupe Machines', () => {
    renderA('/admin/hosts')

    for (const lien of SECTION_MACHINES.liens) {
      expect(screen.getByRole('link', { name: i18n.t(lien.labelKey) })).toBeInTheDocument()
    }
  })

  it("designe l'ecran courant", () => {
    renderA('/admin/billing-offers')

    const courant = screen.getByRole('link', { name: i18n.t('admin.offers.navLabel') })
    expect(courant).toHaveAttribute('aria-current', 'page')
  })

  it('ne rend rien sur un ecran hors groupe', () => {
    const { container } = renderA('/admin/logs')

    expect(container).toBeEmptyDOMElement()
  })

  it('ne confond pas /admin/hosts et /admin/host-profiles', () => {
    // Deux ecrans voisins par le nom, deux groupes differents : un test par
    // prefixe les melangerait.
    expect(sectionDe('/admin/hosts')).toBe(SECTION_MACHINES)
    expect(sectionDe('/admin/host-profiles')).toBe(SECTION_FORFAITS)
  })

  it('tient sur une seule ligne, defilable au doigt', () => {
    // La hauteur du contenu utile ne doit pas dependre du nombre d'ecrans du
    // groupe : sur mobile, un retour a la ligne repousserait la page vers le bas.
    renderA('/admin/billing-catalog')

    const barre = screen.getByRole('navigation')
    expect(barre.className).toContain('overflow-x-auto')
    expect(barre.querySelector('a')?.className).toContain('whitespace-nowrap')
  })
})
