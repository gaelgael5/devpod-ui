/**
 * Collecte des URL dans le FLUX BRUT du terminal.
 *
 * Pourquoi ne pas se fier au détecteur de liens de xterm : il lit le *buffer
 * rendu*. Une URL longue y est repliée sur plusieurs lignes, et sa
 * reconstitution s'est révélée fautive en conditions réelles — des blocs
 * entiers manquaient au milieu, rendant inutilisable l'URL d'authentification
 * de `claude` sur un terminal mobile d'environ 50 colonnes.
 *
 * Le flux, lui, contient l'URL d'un seul tenant : c'est la source de vérité, le
 * buffer n'en est qu'un rendu. On y collecte donc les URL au passage, et on s'en
 * sert pour réparer ce que le détecteur propose au clic.
 */

/* eslint-disable no-control-regex */
/** CSI (couleurs, déplacements) et OSC (titre de fenêtre, hyperliens). */
const ANSI = /\u001b\[[0-?]*[ -/]*[@-~]|\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)?/g
/* eslint-enable no-control-regex */

/** URL http(s) : tout jusqu'au premier blanc ou délimiteur usuel. */
const URL_RE = /https?:\/\/[^\s"'<>`\\]+/g

/** Ponctuation de fin de phrase, qui n'appartient pas à l'URL. */
const TRAILING = /[.,;:!?)\]}]+$/

/** Report conservé d'une trame à l'autre : une URL peut être coupée en deux. */
const TAIL_CHARS = 4_096

/** Nombre d'URL mémorisées, de la plus récente à la plus ancienne. */
const MAX_URLS = 20

export interface LinkCollector {
  /** Alimente le collecteur avec un fragment de flux. */
  push(chunk: string): void
  /** URL vues, la plus récente d'abord. */
  seen(): string[]
  /**
   * URL à ouvrir réellement pour un lien cliqué, potentiellement tronqué ou
   * abîmé par le repli. Retourne `clicked` si rien de mieux n'est connu.
   */
  resolve(clicked: string): string
}

/** Origine + chemin, sans la query — la partie qui survit au repli. */
function originAndPath(raw: string): string | null {
  try {
    const u = new URL(raw)
    return `${u.origin}${u.pathname}`
  } catch {
    return null
  }
}

export function createLinkCollector(): LinkCollector {
  let tail = ''
  const urls: string[] = []

  function record(url: string) {
    const clean = url.replace(TRAILING, '')
    if (!clean.includes('://')) return
    const at = urls.indexOf(clean)
    if (at !== -1) urls.splice(at, 1)
    urls.unshift(clean)
    urls.length = Math.min(urls.length, MAX_URLS)
  }

  return {
    push(chunk: string) {
      if (!chunk) return
      const text = tail + chunk.replace(ANSI, '')

      for (const match of text.matchAll(URL_RE)) {
        const start = match.index
        if (start + match[0].length === text.length) {
          // La correspondance touche la fin du fragment : l'URL est peut-être
          // coupée par la trame. On la garde pour la prochaine passe plutôt que
          // d'enregistrer une version tronquée qui polluerait la résolution.
          tail = text.slice(start)
          return
        }
        record(match[0])
      }

      tail = text.slice(-TAIL_CHARS)
    },

    seen() {
      return [...urls]
    },

    resolve(clicked: string) {
      // Le détecteur a vu juste : rien à réparer.
      if (urls.includes(clicked)) return clicked

      const key = originAndPath(clicked)
      if (!key) return clicked

      // L'origine et le chemin résistent au repli : ils sont en tête d'URL, là
      // où le buffer est encore fidèle. C'est la query, longue, qui est mutilée.
      const candidates = urls.filter((u) => originAndPath(u) === key)
      if (candidates.length === 0) return clicked

      // Une candidate qui prolonge exactement le texte cliqué est la bonne ;
      // sinon la plus récente, c'est-à-dire celle que l'utilisateur a sous
      // les yeux.
      return candidates.find((u) => u.startsWith(clicked)) ?? candidates[0]
    },
  }
}
