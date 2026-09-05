import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

/**
 * Offres d'abonnement : ce que l'on vend, et a quel prix dans chaque devise.
 *
 * Deux regles portees par le serveur et que l'IHM se contente de rendre : une
 * offre sans prix dans aucune devise activee n'est pas publiable, et une offre
 * deja souscrite ne se supprime pas — elle se depublie.
 */

export type HostingType = 'dedie' | 'mutualise'

export interface OfferPrice {
  currency: string
  /**
   * Entier en unites mineures (centimes) — JAMAIS un flottant. Son sens depend
   * du mode de taxe du canal : HT en `automatique`, TTC en `manuel`.
   */
  amount_minor: number
  provider_price_id: string
}

export interface Offer {
  slug: string
  /** Nom court du produit, NON traduit : « Standard », « Max ». */
  label: string
  /** Titre montre au client, lui traduit — `{langue: texte}`. */
  titles: Record<string, string>
  /** Descriptions en markdown, par langue. */
  descriptions: Record<string, string>
  hosting_type: HostingType
  /** Au terme : le forfait repart-il, ou s'arrête-t-il ? */
  tacite_reconduction: boolean
  /** Réservé à une souscription par compte. */
  une_par_compte: boolean
  /** Ordre d'affichage public, croissant : 0 en premier. */
  priorite: number
  /** `null` = illimite. Les deux quotas sont independants. */
  max_workspaces: number | null
  max_hosts_dedies: number | null
  variables: Record<string, string>
  provider_slug: string | null
  published: boolean
  prices: OfferPrice[]
  /** Le montant saisi est-il TTC (true) ou HT (false) ? */
  prices_include_tax: boolean
  /** Deriver les devises sans prix propre du prix par defaut. */
  auto_currencies: boolean
  /** Majoration appliquee aux devises derivees. 1 = neutre. Ce n'est PAS un
   *  taux de change : c'est une majoration commerciale. */
  currency_markup: number | string
  /** Forfait de bienvenue : aucun prix. Un drapeau, et non l'absence de tarif —
   *  une offre payante dont on a oublie le prix est une erreur de saisie. */
  is_free: boolean
  /** Duree du forfait EN JOURS. Tout forfait est borne, gratuit comme payant.
   *  `null` = pas encore renseignee : la publication l'exige. */
  duration_days: number | null
  /** Profils de host que l'offre sait provisionner, DU PLUS PRIORITAIRE AU
   *  MOINS. L'ordre EST la priorite — porter un rang a part se desynchroniserait
   *  de la liste au premier retrait. Vide = brouillon : la publication l'exige. */
  host_profiles: string[]
}

/** Reponse d'enregistrement : l'offre, plus ce qui lui manque pour etre vendable. */
export interface OfferSaved extends Offer {
  devises_manquantes: string[]
}

export function offreVide(): Offer {
  return {
    slug: '',
    label: '',
    titles: {},
    descriptions: {},
    hosting_type: 'mutualise',
    tacite_reconduction: false,
    une_par_compte: false,
    priorite: 100,
    max_workspaces: null,
    max_hosts_dedies: null,
    variables: {},
    provider_slug: null,
    published: false,
    prices: [],
    prices_include_tax: false,
    auto_currencies: false,
    currency_markup: 1,
    is_free: false,
    duration_days: 30,
    host_profiles: [],
  }
}

/**
 * Copie d'une offre existante, prete a etre saisie comme une nouvelle.
 *
 * Trois champs ne se copient PAS, et chacun pour une raison qui coute cher :
 *
 * - `slug` est vide. L'enregistrement est un PUT sur le slug : le garder
 *   ECRASERAIT l'offre source au lieu d'en creer une seconde.
 * - `published` retombe a faux. Cloner une offre publiee puis enregistrer sans
 *   relire pousserait un doublon sur la page publique.
 * - `provider_price_id` est vide. Il designe le prix de l'offre SOURCE chez le
 *   fournisseur ; le recopier ferait pointer deux offres sur le meme tarif.
 *
 * Les objets et tableaux sont copies en PROFONDEUR : un etalement superficiel
 * partagerait les references avec l'offre du cache de requetes, et saisir dans
 * le brouillon modifierait l'original affiche dans la liste.
 */
export function offreClonee(source: Offer): Offer {
  return {
    ...source,
    slug: '',
    published: false,
    titles: { ...source.titles },
    descriptions: { ...source.descriptions },
    variables: { ...source.variables },
    host_profiles: [...source.host_profiles],
    prices: source.prices.map((p) => ({ ...p, provider_price_id: '' })),
  }
}

const CLE_OFFRES = ['admin', 'billing', 'offers'] as const

export function useOffers() {
  return useQuery({
    queryKey: CLE_OFFRES,
    queryFn: () => apiFetchJson<Offer[]>('/admin/billing/offers'),
  })
}

export function useSaveOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (offre: Offer) =>
      apiFetchJson<OfferSaved>(`/admin/billing/offers/${encodeURIComponent(offre.slug)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(offre),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE_OFFRES }),
  })
}

export function useDeleteOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetchVoid(`/admin/billing/offers/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE_OFFRES }),
  })
}
