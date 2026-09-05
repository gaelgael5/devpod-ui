/**
 * Montant lisible depuis des unités mineures.
 *
 * Le nombre de décimales vient d'`Intl` et non d'une division par 100 : le yen
 * n'a pas de sous-unité, et diviser aveuglément afficherait un prix cent fois
 * trop petit.
 */
export function formaterMontant(minor: number, devise: string, langue: string): string {
  const format = new Intl.NumberFormat(langue, { style: 'currency', currency: devise })
  const decimales = format.resolvedOptions().maximumFractionDigits ?? 2
  return format.format(minor / 10 ** decimales)
}
