import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Contract {
  id: string
  label: string
  category: string
  source_url: string | null
  version: string
  created_at: string
  updated_at: string
}

export interface AuthHeader {
  header: string
  value_prefix: string
}

export interface Operation {
  operation_id: string
  method: string
  path: string
  url: string
  summary: string
  body_skeleton?: unknown
  auth_headers?: AuthHeader[]
}

export interface ContractDetail extends Contract {
  raw_spec: unknown
  operations: Operation[]
  servers: string[]
}

export interface HeaderRow {
  name: string
  value?: string | null
  secret_ref?: string | null
  value_prefix?: string
  required?: boolean
  enabled?: boolean
}

export interface Automation {
  id: string
  label: string
  slug: string
  active: boolean
  position: number
  stop_chain: boolean
  event_types: string[]
  delay_minutes: number
  contract_ref: string
  operation_id: string
  url: string
  http_method: string
  body_template: string | null
  filter_contract_ref: string | null
  filter_operation_id: string | null
  filter_url: string | null
  filter_method: string | null
  filter_body: string | null
  filter_jsonpath: string | null
  filter_operator: string | null
  filter_expected: string | null
  headers: HeaderRow[]
  last_seq: number
  pending: number
}

export interface AutomationInput {
  label: string
  slug?: string
  event_types: string[]
  contract_ref: string
  operation_id: string
  url: string
  http_method: string
  body_template?: string | null
  delay_minutes?: number
  position?: number
  stop_chain?: boolean
  headers?: HeaderRow[]
  active?: boolean
  filter_contract_ref?: string | null
  filter_operation_id?: string | null
  filter_url?: string | null
  filter_method?: string | null
  filter_body?: string | null
  filter_jsonpath?: string | null
  filter_operator?: string | null
  filter_expected?: string | null
}

export interface SystemSecret {
  slug: string
  label: string
  secret_type: string
  storage_type: string
}

export interface TestCallResult {
  ok: boolean
  status_code?: number
  body?: string
  error?: string
  evaluation?: { passed?: boolean; matches?: unknown[]; error?: string }
}

export interface Run {
  id: string
  event_seq: number
  dedup_key: string
  status: string
  http_status: number | null
  request_preview: string | null
  response_preview: string | null
  error: string | null
  manual: boolean
  created_at: string
}

const BASE = '/admin/automations'

// ─── Contrats ───────────────────────────────────────────────────────────────

export function useContracts() {
  return useQuery<Contract[]>({
    queryKey: ['automations', 'contracts'],
    queryFn: () => apiFetchJson<Contract[]>(`${BASE}/contracts`),
  })
}

export function useContract(id: string | null) {
  return useQuery<ContractDetail>({
    queryKey: ['automations', 'contracts', id],
    queryFn: () => apiFetchJson<ContractDetail>(`${BASE}/contracts/${id}`),
    enabled: id !== null,
  })
}

export function useCreateContract() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      label: string
      category?: string
      source_url?: string
      raw_spec?: unknown
    }) =>
      apiFetchJson<Contract>(`${BASE}/contracts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'contracts'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useUpdateContract() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string
      body: { label?: string; category?: string; source_url?: string; refresh?: boolean }
    }) =>
      apiFetchJson<Contract>(`${BASE}/contracts/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'contracts'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useRefreshContract() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchJson<Contract>(`${BASE}/contracts/${id}/refresh`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'contracts'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useDeleteContract() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiFetchVoid(`${BASE}/contracts/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'contracts'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

// ─── Automates ────────────────────────────────────────────────────────────────

export function useEventTypes() {
  return useQuery<string[]>({
    queryKey: ['automations', 'event-types'],
    queryFn: () => apiFetchJson<string[]>(`${BASE}/event-types`),
    staleTime: 300_000,
  })
}

export function useEventVariables() {
  return useQuery<Record<string, string[]>>({
    queryKey: ['automations', 'event-variables'],
    queryFn: () => apiFetchJson<Record<string, string[]>>(`${BASE}/event-variables`),
    staleTime: 300_000,
  })
}

export function useAutomations() {
  return useQuery<Automation[]>({
    queryKey: ['automations', 'list'],
    queryFn: () => apiFetchJson<Automation[]>(BASE),
    refetchInterval: 15_000,
  })
}

export function useCreateAutomation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AutomationInput) =>
      apiFetchJson<Automation>(BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'list'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useUpdateAutomation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<AutomationInput> }) =>
      apiFetchJson<Automation>(`${BASE}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'list'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useDeleteAutomation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiFetchVoid(`${BASE}/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'list'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useReorderAutomations() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ordered_ids: string[]) =>
      apiFetchJson(`${BASE}/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ordered_ids }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'list'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

// ─── Runs ─────────────────────────────────────────────────────────────────────

export function useRuns(id: string | null) {
  return useQuery<Run[]>({
    queryKey: ['automations', 'runs', id],
    queryFn: () => apiFetchJson<Run[]>(`${BASE}/${id}/runs`),
    enabled: id !== null,
  })
}

export function useReplayRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ automationId, runId }: { automationId: string; runId: string }) =>
      apiFetchJson(`${BASE}/${automationId}/runs/${runId}/replay`, { method: 'POST' }),
    onSuccess: (_r, v) =>
      qc.invalidateQueries({ queryKey: ['automations', 'runs', v.automationId] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useClearRuns() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiFetchVoid(`${BASE}/${id}/runs`, { method: 'DELETE' }),
    onSuccess: (_r, id) => qc.invalidateQueries({ queryKey: ['automations', 'runs', id] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

// ─── Secrets système (en-têtes d'auth des automates) ───────────────────────────

export function useSystemSecrets() {
  return useQuery<SystemSecret[]>({
    queryKey: ['automations', 'secrets'],
    queryFn: () => apiFetchJson<SystemSecret[]>(`${BASE}/secrets`),
    staleTime: 60_000,
  })
}

export function useCreateSystemSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { slug: string; label: string; value: string }) =>
      apiFetchJson<{ slug: string; ref: string }>(`${BASE}/secrets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'secrets'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useDeleteSystemSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) => apiFetchVoid(`${BASE}/secrets/${slug}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'secrets'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}

// ─── Test d'appel (onglet Filtre) ───────────────────────────────────────────────

export function useTestCall() {
  return useMutation({
    mutationFn: (body: {
      url: string
      http_method: string
      headers?: HeaderRow[]
      body?: string | null
      jsonpath?: string | null
      operator?: string | null
      expected?: string | null
      variables?: Record<string, string>
    }) =>
      apiFetchJson<TestCallResult>(`${BASE}/test-call`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onError: (e: Error) => toast.error(e.message),
  })
}

// ─── Simulation / backfill ─────────────────────────────────────────────────────

export function useInjectTestEvent() {
  return useMutation({
    mutationFn: (body: { kind: 'user' | 'host' | 'workspace' | 'session'; workspace?: string }) =>
      apiFetchJson<{ emitted: string }>(`${BASE}/inject-test-event`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onError: (e: Error) => toast.error(e.message),
  })
}

export function useBackfill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetchJson<{ users: number; hosts: number; workspaces: number; sessions: number }>(
        `${BASE}/backfill`,
        {
          method: 'POST',
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations', 'list'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}
