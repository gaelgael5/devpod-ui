import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
  kind:
    | 'debut_essai'
    | 'activation'
    | 'renouvellement'
    | 'echec_paiement'
    | 'resiliation'
    | 'remboursement'
    | 'litige_ouvert'
    | 'litige_clos'
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

/** Reprise d'un abonnement résilié : acte commercial neuf, prix refigé au
 * tarif du jour, terme qui repart — la page invalide ses caches au succès. */
export function useReprendre() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (subscriptionId: string) =>
      apiFetchJson<Souscription>(
        `/me/subscriptions/${encodeURIComponent(subscriptionId)}/reprendre`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['mes-souscriptions'] })
      void qc.invalidateQueries({ queryKey: ['mon-historique-achats'] })
    },
  })
}

/** Résiliation : la sortie qui rend « sans engagement » vrai. L'abonnement
 * passe résilié (réversible par la reprise) ; le disque est gardé le temps de
 * la rétention. */
export function useResilier() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (subscriptionId: string) =>
      apiFetchJson<Souscription>(
        `/me/subscriptions/${encodeURIComponent(subscriptionId)}/resilier`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['mes-souscriptions'] })
      void qc.invalidateQueries({ queryKey: ['mon-historique-achats'] })
    },
  })
}
