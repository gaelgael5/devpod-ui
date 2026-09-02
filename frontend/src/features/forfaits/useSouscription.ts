import { useMutation, useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

/** Ce dont l'écran d'engagement a besoin pour se pré-remplir. */
export interface ContexteSouscription {
  /** Déduit de la connexion, `null` si la déduction n'est pas fiable. */
  pays_devine: string | null
  /** Pays ACTIVÉS uniquement : proposer un pays où l'on ne vend pas mènerait au refus. */
  pays: { code: string; label: string }[]
  devise_par_defaut: string | null
  devises: string[]
}

export interface Abonnement {
  id: string
  offer_slug: string
  state: string
  country_code: string
  currency: string
  amount_minor: number
  ends_at: string | null
}

export function useContexteSouscription() {
  return useQuery<ContexteSouscription>({
    queryKey: ['souscription-contexte'],
    queryFn: () => apiFetchJson<ContexteSouscription>('/me/subscriptions/contexte'),
    // Le pays déduit dépend de la connexion : le remesurer à chaque montage
    // n'apporte rien, mais le figer trop longtemps le rendrait faux après un
    // changement de réseau.
    staleTime: 60 * 1000,
  })
}

export function useSouscrire() {
  return useMutation({
    mutationFn: (demande: { offer_slug: string; country_code: string; currency: string }) =>
      apiFetchJson<Abonnement>('/me/subscriptions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(demande),
      }),
  })
}
