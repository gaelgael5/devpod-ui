import { useEffect, useState } from 'react'

/** Géométrie de la zone réellement visible de la fenêtre. */
export interface VueVisuelle {
  /** Hauteur visible, clavier mobile déduit. */
  hauteur: number
  /** Haut de la zone visible dans le DOCUMENT (`pageTop`), en px. */
  haut: number
}

/**
 * Géométrie reellement visible de la fenetre, clavier mobile deduit.
 *
 * Pourquoi ce hook existe : sur iOS, ouvrir le clavier ne change NI la hauteur
 * du viewport de mise en page, NI `100vh`. Le clavier se pose par-dessus la
 * page, qui garde sa taille — un conteneur en `h-screen` continue donc de
 * s'etendre sous lui, et tout son bas devient invisible. Pour un terminal, ce
 * bas est precisement ce qui compte : le prompt, la ligne de statut tmux et la
 * barre de touches.
 *
 * La hauteur ne suffit pas : pour reveler la zone de saisie, Safari DEPLACE
 * aussi la fenetre visible — pan du viewport visuel ou defilement du document.
 * Un conteneur ancre en haut du document se retrouve alors decale par rapport a
 * ce que l'utilisateur voit. `haut` (= `pageTop`, position du haut visible dans
 * le document) donne de quoi compenser : translater le conteneur d'autant le
 * ramene exactement sous les yeux.
 *
 * `visualViewport` est la seule source qui reflete cette zone.
 *
 * Retourne `null` quand l'API n'existe pas : l'appelant garde alors son
 * dimensionnement CSS d'origine plutot qu'une geometrie inventee.
 */
export function useVisualViewport(): VueVisuelle | null {
  const [geometrie, setGeometrie] = useState<VueVisuelle | null>(() => {
    const vue = window.visualViewport
    return vue ? { hauteur: vue.height, haut: vue.pageTop } : null
  })

  useEffect(() => {
    const vue = window.visualViewport
    if (!vue) return

    // Meme geometrie -> meme objet : React saute le re-rendu, et les
    // `window.scroll` frequents ne coutent rien.
    const relever = () =>
      setGeometrie((prec) =>
        prec && prec.hauteur === vue.height && prec.haut === vue.pageTop
          ? prec
          : { hauteur: vue.height, haut: vue.pageTop },
      )
    // `scroll` autant que `resize` : iOS deplace le viewport visuel sans le
    // redimensionner quand on fait defiler pendant que le clavier est ouvert.
    vue.addEventListener('resize', relever)
    vue.addEventListener('scroll', relever)
    // Safari peut aussi faire defiler le DOCUMENT pour reveler la saisie :
    // `pageTop` change alors sans aucun evenement `visualViewport`.
    window.addEventListener('scroll', relever)
    // La premiere mesure a pu etre prise avant la mise en page.
    relever()

    return () => {
      vue.removeEventListener('resize', relever)
      vue.removeEventListener('scroll', relever)
      window.removeEventListener('scroll', relever)
    }
  }, [])

  return geometrie
}
