import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

/** Type d'agent IA (spec 35) : fichier de config MCP rendu par template Jinja2. */
export interface AgentTypeAdmin {
  id: string
  label: string
  filename: string
  template: string
  target_path: string
  enabled: boolean
  created_at: string
  updated_at: string | null
}

export interface AgentTypeBody {
  id: string
  label: string
  filename: string
  template: string
  target_path: string
  enabled: boolean
}

const QK = ['admin', 'agent-types'] as const

export function useAdminAgentTypes() {
  const qc = useQueryClient()

  const typesQuery = useQuery<AgentTypeAdmin[]>({
    queryKey: QK,
    queryFn: () => apiFetchJson<AgentTypeAdmin[]>('/admin/agent-types'),
  })

  const addType = useMutation({
    mutationFn: (body: AgentTypeBody) =>
      apiFetchJson<AgentTypeAdmin>('/admin/agent-types', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })

  const updateType = useMutation({
    mutationFn: ({ id, ...body }: AgentTypeBody) =>
      apiFetchJson<AgentTypeAdmin>(`/admin/agent-types/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })

  const deleteType = useMutation({
    mutationFn: (id: string) =>
      apiFetchVoid(`/admin/agent-types/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })

  /** Rendu du template courant avec un contexte factice — 422 = erreur Jinja. */
  const preview = useMutation({
    mutationFn: ({ id, template }: { id: string; template: string }) =>
      apiFetchJson<{ content: string }>(
        `/admin/agent-types/${encodeURIComponent(id)}/preview`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ template }),
        },
      ),
  })

  return { typesQuery, addType, updateType, deleteType, preview }
}
