import type { Dispatch, SetStateAction } from 'react'
import type { Offer } from './useBillingOffers'

/** Langue toujours presente : c'est le repli quand la langue du visiteur manque. */
export const LANGUE_PIVOT = 'en'

/** Langues proposees a l'ajout. Volontairement courte : on traduit ce qu'on
 *  vend, pas tout ce qui existe. */
export const LANGUES_CONNUES = ['en', 'fr', 'de', 'es', 'it', 'nl', 'pt']

/** Brouillon partage par les onglets de l'editeur.
 *
 *  L'etat vit dans la page, pas dans les onglets : passer d'un onglet a l'autre
 *  ne doit rien perdre, et l'enregistrement part d'un seul objet. */
export interface OngletProps {
  brouillon: Offer
  setBrouillon: Dispatch<SetStateAction<Offer>>
}

/** "12,34" saisi → 1234 centimes. L'arrondi se fait ici, une seule fois. */
export function enMineur(saisi: string): number {
  return Math.round(Number(saisi.replace(',', '.')) * 100)
}

export function enMajeur(minor: number): string {
  return (minor / 100).toFixed(2)
}
