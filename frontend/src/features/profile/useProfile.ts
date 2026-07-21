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
