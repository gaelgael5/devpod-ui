import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

export interface UserService {
  id: string
  owner_login: string
  name: string
  url: string
  mcp_profile_id: string | null
  mcp_profile_name: string | null
  created_at: string
  updated_at: string | null
}

export interface ServiceBody {
  name: string
  url: string
  mcp_profile_id: string
}

const QK = {
  list: () => ['services'] as const,
}

export function useServices() {
  return useQuery({
    queryKey: QK.list(),
    queryFn: () => apiFetchJson<UserService[]>('/me/services'),
  })
}

export function useCreateService() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ServiceBody) =>
      apiFetchJson<{ id: string }>('/me/services', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useUpdateService() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: ServiceBody & { id: string }) =>
      apiFetchJson<{ id: string }>(`/me/services/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useDeleteService() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchVoid(`/me/services/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}
