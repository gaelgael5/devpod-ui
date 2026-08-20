/**
 * Ouverture d'un lien détecté dans un terminal.
 *
 * Le contenu d'un terminal n'est PAS de confiance : c'est la sortie brute d'un
 * processus distant. On n'ouvre donc que `http`/`https` — un `javascript:` ou un
 * `file:` affiché par une commande ne doit pas devenir cliquable.
 *
 * `noopener,noreferrer` : sans `noopener`, la page ouverte garde une référence
 * `window.opener` vers le portail et peut le rediriger (tabnabbing).
 */

const ALLOWED_PROTOCOLS = new Set(['http:', 'https:'])

/** L'URI est-elle sûre à ouvrir depuis un terminal ? */
export function isOpenableLink(uri: string): boolean {
  try {
    return ALLOWED_PROTOCOLS.has(new URL(uri).protocol)
  } catch {
    // URL non parsable : on n'ouvre pas.
    return false
  }
}

/** Ouvre le lien dans un nouvel onglet. Sans effet si le schéma n'est pas autorisé. */
export function openTerminalLink(uri: string): boolean {
  if (!isOpenableLink(uri)) {
    console.warn('[terminal] lien ignoré (schéma non autorisé)', uri)
    return false
  }
  window.open(uri, '_blank', 'noopener,noreferrer')
  return true
}
