import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import i18n from '@/i18n'
import { apiFetchJson } from '@/shared/api/client'

/**
 * Culture de l'utilisateur — la langue qu'il a CHOISIE, pas celle que son
 * navigateur devine.
 *
 * i18next memorise la langue courante dans le localStorage : pratique, mais
 * local a un navigateur et perdu au premier nettoyage de cache. La culture,
 * elle, vit en base (`UserConfig.culture`) et sert au-dela de l'ecran — c'est
 * elle qui choisit le gabarit d'un message envoye a l'utilisateur (templates
 * Jinja indexes par `(key, culture)`).
 *
 * La base fait donc foi ; le localStorage n'est qu'un cache d'affichage.
 */

export const CULTURES = ['fr', 'en'] as const
export type Culture = (typeof CULTURES)[number]

interface ConfigUtilisateur {
  culture: string
}

const CLE = ['me-config'] as const

export function useMyCulture() {
  return useQuery({
    queryKey: CLE,
    queryFn: () => apiFetchJson<ConfigUtilisateur>('/me/config'),
    staleTime: 5 * 60 * 1000,
    select: (cfg) => cfg.culture,
  })
}

export function useSetCulture() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (culture: Culture) =>
      apiFetchJson<ConfigUtilisateur>('/me/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ culture }),
      }),
    onSuccess: (cfg) => {
      qc.setQueryData(CLE, cfg)
      // L'ecran suit immediatement : enregistrer sans appliquer donnerait
      // l'impression que le choix n'a pas ete pris en compte.
      void i18n.changeLanguage(cfg.culture)
    },
  })
}
