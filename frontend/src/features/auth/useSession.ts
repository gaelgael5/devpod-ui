import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import type { UserInfo } from '@/store/user'

export function useSession() {
  return useQuery<UserInfo>({
    queryKey: ['session'],
    queryFn: () => apiFetchJson<UserInfo>('/me'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}
