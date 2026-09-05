/**
 * Comparaison de limites mémoire Docker, miroir du backend
 * (`config.models.memoire_en_octets`). Sert à signaler un dépassement du
 * plafond du nœud AVANT l'envoi ; le refus qui fait foi reste le 422 backend.
 */

const UNITES: Record<string, number> = { b: 1, k: 1024, m: 1024 ** 2, g: 1024 ** 3, '': 1 }
const RE = /^[0-9]+[bkmg]?$/

/** Octets d'une limite Docker, ou null si vide/non conforme (un entier nu = octets). */
export function memoireEnOctets(v: string): number | null {
  const s = v.trim().toLowerCase()
  if (!RE.test(s)) return null
  const unite = 'bkmg'.includes(s[s.length - 1]) ? s[s.length - 1] : ''
  const nombre = unite ? s.slice(0, -1) : s
  return Number(nombre) * UNITES[unite]
}

/**
 * Vrai si `demande` excède strictement `plafond`. Un plafond vide ne borne
 * rien ; une demande vide ne dépasse pas (elle sera bornée au plafond côté
 * serveur).
 */
export function memoireDepassePlafond(demande: string, plafond: string): boolean {
  const p = memoireEnOctets(plafond)
  const d = memoireEnOctets(demande)
  if (p === null || d === null) return false
  return d > p
}
