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
// --- Sonde temporaire (diag decalage clavier iOS, 04/09/2026) ---------------
// Le correctif translateY(pageTop) ne suffit pas sur iPhone : il faut voir ce
// qui BOUGE reellement a l'ouverture du clavier. Trois mecanismes possibles,
// dont un invisible pour visualViewport : Safari peut faire defiler un ancetre
// `overflow:hidden` pour reveler la saisie (scrollTop interne, que rien ne
// remet a zero). On trace tout vers Faro -> Loki a chaque evenement de
// geometrie. A RETIRER une fois le decalage clavier corrige et valide.
let sondesRestantes = 80

function sonderDecalage(source: string, vue: VisualViewport): void {
  if (sondesRestantes <= 0) return
  sondesRestantes--
  // Conteneurs internes defiles : le coupable typique du "tout remonte".
  const internes: string[] = []
  for (const el of Array.from(document.querySelectorAll<HTMLElement>('div, main, body, html'))) {
    if (el.scrollTop > 0)
      internes.push(`${el.tagName.toLowerCase()}.${(el.className || '').split(' ')[0]}=${Math.round(el.scrollTop)}`)
  }
  console.warn(
    `terminal_diag: viewport ${JSON.stringify({
      source,
      h: Math.round(vue.height),
      pageTop: Math.round(vue.pageTop),
      offsetTop: Math.round(vue.offsetTop),
      scrollY: Math.round(window.scrollY),
      innerH: window.innerHeight,
      internes: internes.slice(0, 6),
    })}`,
  )
}

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
    const relever = (source: string) => () => {
      sonderDecalage(source, vue)
      setGeometrie((prec) =>
        prec && prec.hauteur === vue.height && prec.haut === vue.pageTop
          ? prec
          : { hauteur: vue.height, haut: vue.pageTop },
      )
    }
    // `scroll` autant que `resize` : iOS deplace le viewport visuel sans le
    // redimensionner quand on fait defiler pendant que le clavier est ouvert.
    const surResize = relever('vv_resize')
    const surScroll = relever('vv_scroll')
    // Safari peut aussi faire defiler le DOCUMENT pour reveler la saisie :
    // `pageTop` change alors sans aucun evenement `visualViewport`.
    const surScrollFenetre = relever('win_scroll')
    // Le scroll d'un conteneur interne ne remonte pas a `window` sans capture :
    // c'est precisement le mecanisme qu'on soupconne (sonde).
    const surScrollCapture = relever('scroll_capture')
    vue.addEventListener('resize', surResize)
    vue.addEventListener('scroll', surScroll)
    window.addEventListener('scroll', surScrollFenetre)
    document.addEventListener('scroll', surScrollCapture, true)
    // La premiere mesure a pu etre prise avant la mise en page.
    relever('montage')()

    return () => {
      vue.removeEventListener('resize', surResize)
      vue.removeEventListener('scroll', surScroll)
      window.removeEventListener('scroll', surScrollFenetre)
      document.removeEventListener('scroll', surScrollCapture, true)
    }
  }, [])

  return geometrie
}
