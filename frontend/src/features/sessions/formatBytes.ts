/** Octets → unité lisible. `null`/`undefined` → « ? ».
 *
 * On ne rend JAMAIS « 0 o » pour une valeur inconnue : afficher un espace libre
 * nul alors qu'on n'en sait rien ferait croire à un disque plein.
 *
 * Fichier séparé du composant : un module qui exporte autre chose que des
 * composants casse le Fast Refresh (règle react-refresh/only-export-components).
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '?'
  const units = ['o', 'Ko', 'Mo', 'Go', 'To']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value >= 10 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`
}
