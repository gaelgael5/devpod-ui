import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface UserProfile {
  login: string
  email: string
  display_name: string
}

export function useProfile() {
  return useQuery<UserProfile>({
    queryKey: ['me-profile'],
    queryFn: () => apiFetchJson<UserProfile>('/me/profile'),
    staleTime: 60 * 1000,
  })
}

export function useUpdateProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (display_name: string) =>
      apiFetchJson<UserProfile>('/me/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name }),
      }),
    onSuccess: (data) => {
      qc.setQueryData(['me-profile'], data)
    },
  })
}
