/**
 * Defilement de l'historique tmux au geste.
 *
 * Pourquoi ce module existe : sous tmux, xterm n'a AUCUN historique a faire
 * defiler. tmux occupe l'ecran alterne, le scrollback du terminal reste vide, et
 * le glissement du doigt ne produit rien.
 *
 * La molette, elle, produit PIRE que rien. Sur un tampon sans scrollback, xterm
 * la traduit en touches de curseur (`ESC [ A` / `ESC [ B`) qu'il ecrit dans la
 * session — le shell et Claude Code y lisent un parcours de l'historique des
 * COMMANDES. C'est le comportement que `attachCustomWheelEventHandler` coupe
 * dans FullscreenTerminal ; sans cela, ce module defilerait pendant que
 * l'application rappelle ses commandes precedentes.
 *
 * L'historique vit dans le copy-mode de tmux. On traduit le geste en touches
 * plutot que d'activer `mouse on` cote tmux : celui-ci capterait les evenements
 * souris et casserait la selection de xterm, donc la copie.
 *
 * Trois bindings tmux par defaut, verifies contre un vrai client :
 *
 *     prefixe + [   copy-mode              entre SANS sauter ; rejoue en
 *                                          copy-mode, PRESERVE la position
 *     C-Up          send-keys -X scroll-up      une ligne
 *     C-Down        send-keys -X scroll-down    une ligne
 *
 * UN SEUL JETON PAR FRAME — contrainte mesuree, pas esthetique. Le PTY regroupe
 * les ecritures rapprochees en une seule lecture, et tmux perd alors les touches
 * repetees : 10 `C-Up` d'affilee ne font defiler que de 2 lignes, que les
 * touches soient concatenees ou ecrites separement sans delai. Espacees, meme de
 * 5 ms, les 10 passent. On emet donc un jeton par frame et on ecoule le reste
 * aux frames suivantes — ce qui donne aussi un mouvement continu plutot que des
 * sauts de page.
 */

/** Prefixe tmux (Ctrl+B) puis `[` : entre en copy-mode sans deplacer la vue. */
export const ENTER_COPY = '\x02['
/** Ctrl+Fleche haut : remonte d'une ligne. */
export const LINE_UP = '\x1b[1;5A'
/** Ctrl+Fleche bas : redescend d'une ligne. */
export const LINE_DOWN = '\x1b[1;5B'
/**
 * Sortie du copy-mode. `q` y est lie dans les deux jeux de bindings tmux
 * (emacs et vi), contrairement a Echap.
 *
 * Sans sortie explicite, tmux RESTE en copy-mode apres le geste : il y absorbe
 * la saisie au lieu de la transmettre a l'application, et l'utilisateur tape
 * dans le vide sans comprendre pourquoi — la frappe part bien cote navigateur,
 * elle meurt cote tmux.
 */
export const EXIT_COPY = 'q'

/** Pixels de geste pour une ligne — proche de la hauteur d'une ligne a 13 px. */
export const LINE_PX = 20

/** Plafond de l'accumulateur : un geste ample ne doit pas defiler pendant des secondes. */
export const MAX_LIGNES_EN_ATTENTE = 50

/**
 * `deltaY` d'un evenement molette, converti en PIXELS.
 *
 * `deltaY` n'a pas d'unite fixe : `deltaMode` dit laquelle. Firefox, et Chrome
 * sur certaines configurations, rendent des LIGNES (`deltaMode` 1) — un cran
 * vaut alors `3`, pas `100`. Lu comme des pixels, un cran n'apportait que trois
 * pixels la ou il en faut vingt pour une ligne : il fallait SEPT crans pour que
 * l'ecran bouge d'un cran. Le geste semblait sans effet, alors qu'il etait
 * seulement divise par trente.
 *
 * Le glissement du doigt, lui, est en pixels par nature. D'ou un defilement
 * tactile correct et une molette inerte sur la meme session — ce qui masquait
 * la cause.
 *
 * `lignesParPage` sert au mode PAGE (`deltaMode` 2, molettes a cran large) :
 * c'est la hauteur de l'ecran, en lignes.
 */
export function pixelsDeMolette(
  e: { deltaY: number; deltaMode: number },
  lignesParPage: number,
): number {
  if (e.deltaMode === 1) return e.deltaY * LINE_PX
  if (e.deltaMode === 2) return e.deltaY * LINE_PX * lignesParPage
  return e.deltaY
}

/**
 * Deplacement a franchir avant qu'un contact devienne un glissement.
 *
 * Sans ce seuil, `touchMove` consommait le geste des le premier pixel et
 * l'appelant supprimait l'evenement — ce qui, sur iOS, supprime aussi le clic
 * synthetise dont xterm a besoin pour prendre le focus et pour selectionner un
 * mot au double-clic. Un doigt ne se pose jamais parfaitement immobile : la
 * tape la plus franche bouge de quelques pixels, et devenait un glissement.
 */
export const DRAG_SLOP_PX = 12

export interface HistoryScroller {
  /** Molette. Retourne `true` si le geste est consomme (defilement natif a supprimer). */
  wheel(deltaY: number): boolean
  /** Debut d'un glissement tactile. */
  touchStart(clientY: number): void
  /** Glissement en cours. Retourne `true` si le geste est consomme. */
  touchMove(clientY: number): boolean
  /** Fin du glissement. */
  touchEnd(): void
  /**
   * Quitte le copy-mode si un geste y a fait entrer. Retourne `true` si une
   * sortie vient d'etre emise — l'appelant doit alors espacer ce qu'il envoie
   * ensuite (cf. la note sur les lectures PTY groupees).
   */
  exitCopyMode(): boolean
}

interface Options {
  /** Le tampon alterne est-il actif ? (tmux, TUI plein ecran) */
  isAlternate: () => boolean
  /** Ecrit dans l'entree standard de la session. */
  send: (data: string) => void
  /** Planifie l'emission suivante. Injectable pour les tests. */
  schedule?: (cb: () => void) => void
  /**
   * L'application suit-elle la souris (mouse tracking actif) ?
   *
   * Une TUI plein ecran comme Claude Code vit dans l'ecran alterne du pane et
   * redessine sur place : l'historique tmux reste VIDE (copy-mode a `[0/0]`,
   * mesure le 05/09) — le copy-mode n'a rien a defiler. Cette TUI suit la
   * souris et defile son propre transcript sur les evenements molette : le
   * geste doit alors parler a L'APPLICATION, pas a tmux.
   */
  capteSouris?: () => boolean
  /**
   * Sequence molette a envoyer a l'application (SGR, position comprise).
   * Fournie par l'appelant, qui connait la geometrie du terminal.
   */
  sequenceMolette?: (up: boolean) => string
}

const parDefaut = (cb: () => void) => {
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(cb)
  else setTimeout(cb, 16)
}

export function createHistoryScroller({
  isAlternate,
  send,
  schedule = parDefaut,
  capteSouris = () => false,
  sequenceMolette = () => '',
}: Options): HistoryScroller {
  let acc = 0
  let lastY: number | null = null
  /** Point de pose du doigt, pour mesurer le franchissement du seuil. */
  let departY: number | null = null
  /** Le seuil est-il franchi ? Tant que non, le contact peut encore etre une tape. */
  let glisse = false
  let planifie = false
  /** Copy-mode deja demande pour la salve en cours. */
  let entre = false
  /** tmux est-il en copy-mode ? Persiste APRES le geste, contrairement a `entre`. */
  let enCopyMode = false

  const plafond = LINE_PX * MAX_LIGNES_EN_ATTENTE

  function emettre() {
    planifie = false
    if (!isAlternate()) {
      acc = 0
      entre = false
      return
    }

    // Application qui suit la souris : le defilement lui appartient. On emet
    // des evenements molette (une TUI comme Claude Code y defile son
    // transcript) et on ne touche jamais au copy-mode — son historique est
    // vide, et le `q` de sortie taperait dans l'application.
    const molette = capteSouris()

    if (acc <= -LINE_PX) {
      if (molette) {
        acc += LINE_PX
        send(sequenceMolette(true))
      } else if (!entre) {
        // L'entree en copy-mode occupe sa propre emission : concatenee a une
        // touche de defilement, elle la ferait perdre (meme lecture PTY).
        entre = true
        enCopyMode = true
        send(ENTER_COPY)
      } else {
        acc += LINE_PX
        send(LINE_UP)
      }
    } else if (acc >= LINE_PX) {
      // Pas d'entree en copy-mode vers le bas : sinon un glissement vers le bas
      // depuis la vue directe y ferait entrer, figeant l'affichage sans raison.
      acc -= LINE_PX
      send(molette ? sequenceMolette(false) : LINE_DOWN)
    } else {
      entre = false
      return
    }

    planifier()
  }

  function planifier() {
    if (planifie) return
    // Rien a ecouler tant qu'on n'atteint pas une ligne pleine.
    if (acc > -LINE_PX && acc < LINE_PX) return
    planifie = true
    schedule(emettre)
  }

  /** `delta` positif = vers le contenu recent (on redescend). */
  function feed(delta: number): boolean {
    // Hors tampon alterne, xterm a un vrai scrollback : on le laisse faire.
    if (!isAlternate()) return false

    acc = Math.max(-plafond, Math.min(plafond, acc + delta))
    planifier()
    // Consomme des que le tampon alterne est actif, meme sans ligne atteinte :
    // sinon le reliquat de geste declencherait le defilement natif du navigateur.
    return true
  }

  return {
    wheel: (deltaY) => feed(deltaY),

    touchStart(clientY) {
      lastY = clientY
      departY = clientY
      glisse = false
    },

    touchMove(clientY) {
      if (lastY === null || departY === null) return false
      // Sous le seuil, le contact reste une tape : on ne consomme rien, et le
      // navigateur garde le droit de synthetiser son clic.
      if (!glisse) {
        if (Math.abs(clientY - departY) < DRAG_SLOP_PX) return false
        // Le glissement part du point de franchissement, pas du point de pose :
        // sinon il commencerait par un saut de la valeur du seuil. `feed(0)`
        // n'accumule rien et repond ce que repondra la suite du geste — non
        // consomme hors tampon alterne, ou xterm a son propre scrollback.
        glisse = true
        lastY = clientY
        return feed(0)
      }
      // Le doigt descend => on remonte dans l'historique : signe inverse.
      const consomme = feed(-(clientY - lastY))
      lastY = clientY
      return consomme
    },

    touchEnd() {
      lastY = null
      departY = null
      glisse = false
    },

    exitCopyMode() {
      if (!enCopyMode) return false
      enCopyMode = false
      entre = false
      // Ce qui restait a defiler n'a plus de sens une fois le mode quitte.
      acc = 0
      send(EXIT_COPY)
      return true
    },
  }
}
