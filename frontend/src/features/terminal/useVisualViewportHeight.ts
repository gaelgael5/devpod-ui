import { useEffect, useState } from 'react'

/**
 * Hauteur reellement visible de la fenetre, clavier mobile deduit.
 *
 * Pourquoi ce hook existe : sur iOS, ouvrir le clavier ne change NI la hauteur
 * du viewport de mise en page, NI `100vh`. Le clavier se pose par-dessus la
 * page, qui garde sa taille — un conteneur en `h-screen` continue donc de
 * s'etendre sous lui, et tout son bas devient invisible. Pour un terminal, ce
 * bas est precisement ce qui compte : le prompt, la ligne de statut tmux et la
 * barre de touches.
 *
 * `visualViewport` est la seule source qui reflete la zone laissee libre.
 *
 * Retourne `null` quand l'API n'existe pas : l'appelant garde alors son
 * dimensionnement CSS d'origine plutot qu'une hauteur inventee.
 */
export function useVisualViewportHeight(): number | null {
  const [hauteur, setHauteur] = useState<number | null>(
    () => window.visualViewport?.height ?? null,
  )

  useEffect(() => {
    const vue = window.visualViewport
    if (!vue) return

    const relever = () => setHauteur(vue.height)
    // `scroll` autant que `resize` : iOS deplace le viewport visuel sans le
    // redimensionner quand on fait defiler pendant que le clavier est ouvert.
    vue.addEventListener('resize', relever)
    vue.addEventListener('scroll', relever)
    // La premiere mesure a pu etre prise avant la mise en page.
    relever()

    return () => {
      vue.removeEventListener('resize', relever)
      vue.removeEventListener('scroll', relever)
    }
  }, [])

  return hauteur
}
