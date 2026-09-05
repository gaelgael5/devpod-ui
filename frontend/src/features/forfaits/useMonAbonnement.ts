import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

/** Contrat de `GET /me/subscriptions` — l'abonnement tel que souscrit. */
export interface Souscription {
  id: string
  login: string
  offer_slug: string
  provider_slug: string | null
  state: 'essai' | 'actif' | 'echec_paiement' | 'resilie'
  country_code: string
  currency: string
  /** INSTANTANÉ du prix à la souscription — pas le catalogue d'aujourd'hui. */
  amount_minor: number
  provider_subscription_id: string
  payment_attempts: number
  next_retry_at: string | null
  trial_end: string | null
  current_period_end: string | null
  /** Terme du forfait. `null` = pas encore posé. */
  ends_at: string | null
  state_changed_at: string | null
}

/** Contrat de `GET /me/subscriptions/historique` — ses ACHATS, filtrés serveur. */
export interface EntreeHistorique {
  id: number
  kind: 'debut_essai' | 'activation' | 'renouvellement' | 'echec_paiement' | 'resiliation'
  subscription_id: string | null
  provider_slug: string
  provider_event_id: string
  visibilite: string
  occurred_at: string
  created_at: string
  offer_slug: string | null
  login: string
}

export function useMesSouscriptions() {
  return useQuery<Souscription[]>({
    queryKey: ['mes-souscriptions'],
    queryFn: () => apiFetchJson<Souscription[]>('/me/subscriptions'),
  })
}

export function useMonHistorique() {
  return useQuery<EntreeHistorique[]>({
    queryKey: ['mon-historique-achats'],
    queryFn: () => apiFetchJson<EntreeHistorique[]>('/me/subscriptions/historique'),
  })
}
