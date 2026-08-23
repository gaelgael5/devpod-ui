import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface UserProfile {
  login: string
  email: string
  display_name: string
  // Identité (GUID) propagée aux services MCP (on-behalf-of). '' = non définie → rien propagé.
  identity: string
}

export function useProfile() {
  return useQuery<UserProfile>({
    queryKey: ['me-profile'],
    queryFn: () => apiFetchJson<UserProfile>('/me/profile'),
    staleTime: 60 * 1000,
  })
}

/** Claims essentiels du jeton OIDC (jamais le jeton brut) — pour affichage/copie. */
export interface TokenClaims {
  claims: Record<string, string>
}

export function useTokenClaims() {
  return useQuery<TokenClaims>({
    queryKey: ['me-token-claims'],
    queryFn: () => apiFetchJson<TokenClaims>('/me/token-claims'),
    staleTime: 5 * 60 * 1000,
  })
}

export interface MyTermixInstance {
  id: string
  name: string
  url: string
}

/** Serveurs Termix effectifs de l'utilisateur (lecture seule, spec 18 T4b). */
export function useMyTermixInstances() {
  return useQuery<MyTermixInstance[]>({
    queryKey: ['me-termix-instances'],
    queryFn: () => apiFetchJson<MyTermixInstance[]>('/me/termix-instances'),
    staleTime: 5 * 60 * 1000,
  })
}

export type ProfileUpdate = { display_name?: string; email?: string; identity?: string }

export function useUpdateProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: ProfileUpdate) =>
      apiFetchJson<UserProfile>('/me/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }),
    onSuccess: (data) => {
      qc.setQueryData(['me-profile'], data)
    },
  })
}
