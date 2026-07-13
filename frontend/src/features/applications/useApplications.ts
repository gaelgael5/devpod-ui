import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

export interface KioskApplication {
  id: number
  name: string
  url: string
  icon: string
  position: number
}

export interface KioskApplicationBody {
  name: string
  url: string
  icon: string
}

export function useApplications() {
  return useQuery<KioskApplication[]>({
    queryKey: ['kiosk-applications'],
    queryFn: () => apiFetchJson<KioskApplication[]>('/applications'),
    staleTime: 60 * 1000,
  })
}

export function useAddApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (app: KioskApplicationBody) =>
      apiFetchJson<KioskApplication>('/applications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(app),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kiosk-applications'] })
    },
  })
}

export function useUpdateApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...app }: KioskApplicationBody & { id: number }) =>
      apiFetchJson<KioskApplication>(`/applications/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(app),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kiosk-applications'] })
    },
  })
}

export async function probeFavicon(url: string): Promise<string | null> {
  const res = await apiFetchJson<{ favicon: string | null }>(
    `/applications/favicon?url=${encodeURIComponent(url)}`
  )
  return res.favicon
}

export function useDeleteApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetchVoid(`/applications/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kiosk-applications'] })
    },
  })
}
