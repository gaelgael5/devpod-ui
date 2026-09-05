import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

/**
 * Catalogue de facturation : pays, devises, canaux de paiement.
 *
 * Ce sont les donnees qui decident de ce qu'on peut vendre, ou, et par quel
 * canal. Le serveur porte les regles (une seule devise par defaut, un canal
 * reference ne se supprime pas) : l'IHM ne les redouble pas, elle affiche le
 * refus tel qu'il arrive.
 */

export interface Country {
  /** Code ISO-3166-1 alpha-2. C'est l'identite : il ne se renomme pas. */
  code: string
  label: string
  enabled: boolean
}

export interface Currency {
  /** Code ISO-4217, trois lettres majuscules. */
  code: string
  enabled: boolean
  /** Une seule devise porte le defaut : celle qu'on propose faute de mieux. */
  is_default: boolean
}

export type TaxMode = 'automatique' | 'manuel'
export type ProviderKind = 'stripe'

export interface PaymentProvider {
  /** Identifiant de l'INSTANCE : deux comptes Stripe coexistent. */
  slug: string
  /** Discriminant d'adaptateur. */
  kind: ProviderKind
  label: string
  tax_mode: TaxMode
  enabled: boolean
  config: Record<string, string>
  /** Reference vers la table des secrets. JAMAIS la cle elle-meme. */
  secret_slug: string
}

export interface CountryProvider {
  country_code: string
  provider_slug: string
  /** Ordre d'essai, croissant — un canal defaillant ne doit pas emporter la vente. */
  priority: number
}

export interface SystemSecret {
  slug: string
  label: string
  secret_type: string
  storage_type: string
}

export function paysVide(): Country {
  return { code: '', label: '', enabled: true }
}

export function canalVide(): PaymentProvider {
  return {
    slug: '',
    kind: 'stripe',
    label: '',
    tax_mode: 'manuel',
    enabled: true,
    config: {},
    secret_slug: '',
  }
}

const CLE_PAYS = ['admin', 'billing', 'countries'] as const
const CLE_CANAUX = ['admin', 'billing', 'providers'] as const

// ─── Pays ────────────────────────────────────────────────────────────────────

export function useCountries() {
  return useQuery({
    queryKey: CLE_PAYS,
    queryFn: () => apiFetchJson<Country[]>('/admin/billing/countries'),
  })
}

export function useSaveCountry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (pays: Country) =>
      apiFetchJson<Country>(`/admin/billing/countries/${encodeURIComponent(pays.code)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pays),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE_PAYS }),
  })
}

export function useDeleteCountry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (code: string) =>
      apiFetchVoid(`/admin/billing/countries/${encodeURIComponent(code)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE_PAYS }),
  })
}

// ─── Devises acceptees par l'application ─────────────────────────────────────
//
// Jeu GLOBAL, plus rattache a un pays : ce que la plateforme sait encaisser ne
// depend pas de l'endroit ou vit l'acheteur.

const CLE_DEVISES = ['admin', 'billing', 'currencies'] as const

export function useCurrencies() {
  return useQuery({
    queryKey: CLE_DEVISES,
    queryFn: () => apiFetchJson<Currency[]>('/admin/billing/currencies'),
  })
}

export function useSetCurrencies() {
  const qc = useQueryClient()
  return useMutation({
    // Le serveur remplace le jeu entier : envoyer un delta laisserait passer un
    // etat transitoire a deux defauts, que l'index partiel refuse.
    mutationFn: (devises: Currency[]) =>
      apiFetchJson<Currency[]>('/admin/billing/currencies', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(devises),
      }),
    onSuccess: (devises) => qc.setQueryData(CLE_DEVISES, devises),
  })
}

// ─── Canaux de paiement ──────────────────────────────────────────────────────

export function useProviders() {
  return useQuery({
    queryKey: CLE_CANAUX,
    queryFn: () => apiFetchJson<PaymentProvider[]>('/admin/billing/providers'),
  })
}

export function useSaveProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (canal: PaymentProvider) =>
      apiFetchJson<PaymentProvider>(`/admin/billing/providers/${encodeURIComponent(canal.slug)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(canal),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE_CANAUX }),
  })
}

export function useDeleteProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetchVoid(`/admin/billing/providers/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CLE_CANAUX }),
  })
}

// ─── Rattachement pays ↔ canaux ──────────────────────────────────────────────

export function useCountryProviders(code: string) {
  return useQuery({
    queryKey: [...CLE_PAYS, code, 'providers'],
    queryFn: () =>
      apiFetchJson<CountryProvider[]>(
        `/admin/billing/countries/${encodeURIComponent(code)}/providers`,
      ),
    enabled: Boolean(code),
  })
}

export function useSetCountryProviders(code: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (rattachements: CountryProvider[]) =>
      apiFetchJson<CountryProvider[]>(
        `/admin/billing/countries/${encodeURIComponent(code)}/providers`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(rattachements),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...CLE_PAYS, code, 'providers'] }),
  })
}

// ─── Secrets systeme (pour designer la cle d'un canal) ───────────────────────

export function useSystemSecrets() {
  return useQuery({
    queryKey: ['admin', 'automations', 'secrets'],
    queryFn: () => apiFetchJson<SystemSecret[]>('/admin/automations/secrets'),
    staleTime: 60 * 1000,
  })
}

// ─── Taux de taxe (mode manuel) ──────────────────────────────────────────────

export interface TaxRate {
  /** `null` tant que le taux n'est pas persiste. */
  id: number | null
  country_code: string
  /** Vide = tout le pays. */
  region: string
  /** 0.2000 = 20 %. Nombre a la lecture, chaine a l'ecriture — jamais arrondi ici. */
  rate: number | string
  label: string
  valid_from: string
  /** `null` = en vigueur. */
  valid_to: string | null
}

function cleTaux(code: string) {
  return [...CLE_PAYS, code, 'tax-rates'] as const
}

export function useTaxRates(code: string) {
  return useQuery({
    queryKey: cleTaux(code),
    queryFn: () =>
      apiFetchJson<TaxRate[]>(`/admin/billing/countries/${encodeURIComponent(code)}/tax-rates`),
    enabled: Boolean(code),
  })
}

export function useAddTaxRate(code: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taux: Omit<TaxRate, 'id'>) =>
      apiFetchJson<TaxRate>(`/admin/billing/countries/${encodeURIComponent(code)}/tax-rates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(taux),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: cleTaux(code) }),
  })
}

/** Seule mutation permise sur un taux : tout le reste passe par un taux neuf. */
export function useCloseTaxRate(code: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, valid_to }: { id: number; valid_to: string }) =>
      apiFetchJson<TaxRate>(`/admin/billing/tax-rates/${id}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ valid_to }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: cleTaux(code) }),
  })
}

export function useDeleteTaxRate(code: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetchVoid(`/admin/billing/tax-rates/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: cleTaux(code) }),
  })
}
