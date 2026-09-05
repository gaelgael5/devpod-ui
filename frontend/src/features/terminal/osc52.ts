/**
 * OSC 52 — le presse-papier réclamé par l'application distante.
 *
 * tmux est déjà configuré pour relayer la séquence (`set-clipboard external`,
 * `terminal-features xterm*:clipboard`), mais xterm.js ne l'implémente pas :
 * elle arrivait jusqu'au navigateur et y était jetée. D'où le « copied ... »
 * affiché par le TUI et un presse-papier système resté vide.
 *
 * Format reçu : `<cibles>;<base64>` — xterm a déjà retiré le `52;` de tête.
 */

/**
 * Au-delà, on refuse.
 *
 * La séquence vient du réseau et finit dans le presse-papier de l'utilisateur :
 * un processus distant qui déraille ne doit pas pouvoir y déverser des mégaoctets.
 * 100 ko couvrent très largement une sélection d'écran.
 */
export const OSC52_MAX_OCTETS = 100_000

export type Osc52Result =
  | { ok: true; texte: string }
  | { ok: false; raison: 'lecture' | 'vide' | 'trop_gros' | 'base64_invalide' }

/** Décode la charge utile d'un OSC 52. Ne lève jamais. */
export function decodeOsc52(charge: string): Osc52Result {
  const separateur = charge.indexOf(';')
  const base64 = separateur === -1 ? charge : charge.slice(separateur + 1)

  // `?` demande la LECTURE du presse-papier. Jamais servie : y répondre livrerait
  // le presse-papier de l'utilisateur — mots de passe compris — au processus
  // distant, sans qu'il en soit informé.
  if (base64 === '?') return { ok: false, raison: 'lecture' }
  // Charge vide : la spec y voit un effacement du presse-papier. On s'en abstient,
  // perdre le contenu courant sur une séquence parasite serait pire que ne rien faire.
  if (!base64) return { ok: false, raison: 'vide' }

  let binaire: string
  try {
    binaire = atob(base64)
  } catch {
    return { ok: false, raison: 'base64_invalide' }
  }
  // Mesuré en OCTETS et non en caractères : la limite protège le presse-papier,
  // et un texte accentué pèse plus que sa longueur décodée ne le laisse croire.
  if (binaire.length > OSC52_MAX_OCTETS) return { ok: false, raison: 'trop_gros' }

  // `atob` rend une chaîne d'octets. La repasser telle quelle au presse-papier
  // rendrait « é » en « Ã© » : il faut la relire comme de l'UTF-8.
  const octets = Uint8Array.from(binaire, (c) => c.charCodeAt(0))
  return { ok: true, texte: new TextDecoder().decode(octets) }
}
