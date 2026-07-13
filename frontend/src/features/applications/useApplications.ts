import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

export interface KioskApplication {
  id: number
  name: string
  url: string
  icon: string
  position: number
}

export interface KioskApplicationCreate {
  name: string
  url: string
  icon: string
}

export function useApplications() {
  return useQuery<KioskApplication[]>({
    queryKey: ['kiosk-applications'],
    queryFn: () => apiFetchJson<KioskApplication[]>('/me/applications'),
    staleTime: 60 * 1000,
  })
}

export function useAddApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (app: KioskApplicationCreate) =>
      apiFetchJson<KioskApplication>('/me/applications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(app),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kiosk-applications'] })
    },
  })
}

export function useDeleteApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetchVoid(`/me/applications/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kiosk-applications'] })
    },
  })
}
