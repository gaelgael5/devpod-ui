import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson } from '@/shared/api/client'

export interface EventsProducerConfig {
  enabled: boolean
  workflow_base_url: string
  source_id: string
  source_uri: string
  events: string[]
  available_events: string[]
  has_secret: boolean
  discovery_url: string
}

export interface EventsProducerUpdate {
  enabled: boolean
  workflow_base_url: string
  source_id: string
  source_uri: string
  events: string[]
  secret?: string
}

export function useAdminWorkflow() {
  return useQuery<EventsProducerConfig>({
    queryKey: ['admin', 'events-producer'],
    queryFn: () => apiFetchJson<EventsProducerConfig>('/admin/events-producer'),
    staleTime: 60_000,
  })
}

export function useSaveWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: EventsProducerUpdate) =>
      apiFetchJson<EventsProducerConfig>('/admin/events-producer', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'events-producer'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export interface TestConnectionResult {
  ok: boolean
  status_code?: number
  event_code: string
  error?: string
}

export function useTestConnection() {
  return useMutation({
    mutationFn: () =>
      apiFetchJson<TestConnectionResult>('/admin/events-producer/test-connection', {
        method: 'POST',
      }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export interface TestEventResult {
  queued: boolean
  event_id: string
  event_code: string
}

export function useSendTestEvent() {
  return useMutation({
    mutationFn: () =>
      apiFetchJson<TestEventResult>('/admin/events-producer/send-test-event', { method: 'POST' }),
    onError: (err: Error) => toast.error(err.message),
  })
}
