import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

export type RuleOperator = 'eq' | 'neq' | 'contains' | 'not_contains'

export interface RuleActionSpec {
  service_id: string | null
  tool: string
  args: Record<string, unknown>
}

export interface RuleConditionSpec extends RuleActionSpec {
  path: string
  operator: RuleOperator
  value: string
}

export interface UserRule {
  id: string
  owner_login: string
  name: string
  enabled: boolean
  event_type: string
  conditions: RuleConditionSpec[]
  actions: RuleActionSpec[]
  next_rule_id: string | null
  created_at: string
  updated_at: string | null
}

export interface RuleBody {
  name: string
  enabled: boolean
  event_type: string
  conditions: RuleConditionSpec[]
  actions: RuleActionSpec[]
  next_rule_id: string | null
}

export interface ServiceTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

export interface ConditionTrace {
  tool: string
  args: Record<string, unknown>
  result: unknown
  ok: boolean
}

export interface ActionTrace {
  tool: string
  args: Record<string, unknown>
  result: unknown
}

export interface RuleTraceEntry {
  rule: string
  conditions: ConditionTrace[]
  matched: boolean
  actions: ActionTrace[]
  chain_stopped?: string
}

export interface RuleTestResult {
  ok: boolean
  error?: string
  traces?: RuleTraceEntry[]
}

const QK = {
  list: () => ['user-rules'] as const,
  events: () => ['user-rules', 'events'] as const,
  tools: (serviceId: string) => ['user-rules', 'service-tools', serviceId] as const,
}

export function useRules() {
  return useQuery({
    queryKey: QK.list(),
    queryFn: () => apiFetchJson<UserRule[]>('/me/rules'),
  })
}

export function useRuleEvents() {
  return useQuery({
    queryKey: QK.events(),
    queryFn: () => apiFetchJson<string[]>('/me/rules/events'),
  })
}

export function useServiceTools(serviceId: string) {
  return useQuery({
    queryKey: QK.tools(serviceId),
    queryFn: () =>
      apiFetchJson<ServiceTool[]>(`/me/services/${encodeURIComponent(serviceId)}/tools`),
    enabled: !!serviceId,
  })
}

export function useCreateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RuleBody) =>
      apiFetchJson<{ id: string }>('/me/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useUpdateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: RuleBody & { id: string }) =>
      apiFetchJson<{ id: string }>(`/me/rules/${encodeURIComponent(id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export function useDeleteRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchVoid(`/me/rules/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.list() }),
  })
}

export interface ServiceCallResult {
  ok: boolean
  error?: string
  args?: Record<string, unknown>
  result?: unknown
}

export function useTestServiceCall() {
  return useMutation({
    mutationFn: ({
      serviceId,
      tool,
      args,
      workspace,
    }: {
      serviceId: string
      tool: string
      args: Record<string, unknown>
      workspace: string | null
    }) =>
      apiFetchJson<ServiceCallResult>(
        `/me/services/${encodeURIComponent(serviceId)}/tools/call`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tool, args, workspace }),
        },
      ),
  })
}

export function useTestRule() {
  return useMutation({
    mutationFn: ({ id, workspace }: { id: string; workspace: string | null }) =>
      apiFetchJson<RuleTestResult>(`/me/rules/${encodeURIComponent(id)}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace }),
      }),
  })
}
