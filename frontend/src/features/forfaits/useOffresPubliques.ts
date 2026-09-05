import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

/** Contrat de la route publique `GET /offers` — la liste blanche côté serveur. */
export interface OffrePubliee {
  slug: string
  titles: Record<string, string>
  descriptions: Record<string, string>
  hosting_type: 'dedie' | 'mutualise'
  /**
   * En mutualisé : quota personnel, `null` = illimité. En dédié : plafond par
   * machine résolu côté serveur (capacité du profil de host bornée par le
   * quota de l'offre), `null` = non renseigné — jamais « illimité ».
   */
  max_workspaces: number | null
  /** `null` = illimité. Nombre de machines dédiées que le forfait permet de posséder. */
  max_hosts_dedies: number | null
  is_free: boolean
  duration_days: number | null
  /** Au terme, le forfait repart-il ? Information matérielle avant de s'engager. */
  tacite_reconduction: boolean
  /** Réservé à une souscription par compte. */
  une_par_compte: boolean
  /** Devise par défaut du catalogue ; `null` si aucune n'est désignée. */
  currency: string | null
  /** Montant tel qu'il est saisi, en unités mineures. `null` = pas de prix dans cette devise. */
  amount_minor: number | null
  /** Sens du montant. Aucune taxe n'est calculée : le pays du visiteur est inconnu. */
  prices_include_tax: boolean
}

/**
 * Offres publiées, servies sans authentification.
 *
 * Contrairement à `/me`, cette route ne rend jamais 401 : elle passe donc par
 * `apiFetchJson` comme le reste de l'application, sans précaution particulière.
 */
export function useOffresPubliques() {
  return useQuery<OffrePubliee[]>({
    queryKey: ['offres-publiques'],
    queryFn: () => apiFetchJson<OffrePubliee[]>('/offers'),
    staleTime: 5 * 60 * 1000,
  })
}
