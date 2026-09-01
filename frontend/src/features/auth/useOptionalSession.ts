import { useQuery } from '@tanstack/react-query'
import { ApiError, apiFetchOptional } from '@/shared/api/client'
import type { UserInfo } from '@/store/user'

/**
 * Session courante, ou `null` si personne n'est connecté — SANS redirection.
 *
 * `useSession` passe par `apiFetch`, qui renvoie tout 401 vers `/auth/login`.
 * Derrière une garde d'authentification c'est ce qu'on veut ; sur une page
 * publique, cela éjecterait le visiteur anonyme vers la connexion avant qu'il
 * ait rien lu — soit exactement ce qu'une landing doit éviter.
 *
 * Ici, un 401 se lit « anonyme », pas « erreur ».
 */
export function useOptionalSession() {
  return useQuery<UserInfo | null>({
    queryKey: ['session-optionnelle'],
    queryFn: async () => {
      const res = await apiFetchOptional('/me')
      // Seul un 401 dit « personne n'est connecte ». Un 500, un 502 de Caddy ou
      // un 503 pendant un redemarrage du portail ne disent rien de la session :
      // les confondre avec l'anonymat ferait passer un utilisateur connecte
      // pour un visiteur, et `staleTime` figerait ce verdict cinq minutes.
      if (res.status === 401) return null
      if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`)
      return (await res.json()) as UserInfo
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}
