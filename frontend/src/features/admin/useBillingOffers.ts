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
  /** `{langue: texte}`. */
  labels: Record<string, string>
  descriptions: Record<string, string>
  hosting_type: HostingType
  /** `null` = illimite. Les deux quotas sont independants. */
  max_workspaces: number | null
  max_hosts_dedies: number | null
  variables: Record<string, string>
  provider_slug: string | null
  published: boolean
  prices: OfferPrice[]
}

/** Reponse d'enregistrement : l'offre, plus ce qui lui manque pour etre vendable. */
export interface OfferSaved extends Offer {
  devises_manquantes: string[]
}

export function offreVide(): Offer {
  return {
    slug: '',
    labels: {},
    descriptions: {},
    hosting_type: 'mutualise',
    max_workspaces: null,
    max_hosts_dedies: null,
    variables: {},
    provider_slug: null,
    published: false,
    prices: [],
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
