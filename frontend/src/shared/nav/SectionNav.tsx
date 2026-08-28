import { NavLink, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { sectionDe } from './sections'

/**
 * Barre de liens vers les ecrans voisins du meme groupe de menu.
 *
 * Sur mobile, atteindre un ecran voisin demandait d'ouvrir le menu profil, puis
 * un sous-menu, puis de viser : trois gestes pour passer d'un ecran a son
 * jumeau. Cette barre les met a un pouce.
 *
 * Une seule ligne, defilable au doigt (`overflow-x-auto`, `whitespace-nowrap`)
 * plutot qu'un retour a la ligne : la hauteur du contenu utile ne doit pas
 * dependre du nombre d'ecrans du groupe. Meme parti pris que la barre tactile
 * du terminal.
 *
 * Rien n'est rendu hors des groupes declares : la barre est montee une fois
 * pour toutes dans la coquille, et se tait la ou elle n'a rien a dire.
 */
export default function SectionNav() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const section = sectionDe(pathname)
  if (!section) return null

  return (
    <nav
      aria-label={t(section.titleKey)}
      // `-mx-3 px-3` : le defilement va jusqu'au bord de l'ecran sur mobile,
      // sans quoi le dernier lien semble coupe par la marge de la page.
      className="-mx-3 mb-4 overflow-x-auto px-3 sm:mx-0 sm:px-0"
    >
      <ul className="flex w-max gap-1.5">
        {section.liens.map((lien) => (
          <li key={lien.path}>
            <NavLink
              to={lien.path}
              className={({ isActive }) =>
                cn(
                  // h-9 : cible tactile confortable sans manger l'ecran.
                  'flex h-9 items-center whitespace-nowrap rounded-md border px-3 text-sm transition-colors',
                  isActive
                    ? 'border-transparent bg-primary text-primary-foreground'
                    : 'bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
                )
              }
              aria-current={pathname === lien.path ? 'page' : undefined}
            >
              {t(lien.labelKey)}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
