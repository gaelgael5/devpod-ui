import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

export interface JinjaTemplate {
  key: string
  culture: string
  body: string
  updated_at?: string
}

const QK = ['jinja-templates']

export function useJinjaTemplates() {
  const qc = useQueryClient()

  const templates = useQuery<JinjaTemplate[]>({
    queryKey: QK,
    queryFn: () => apiFetchJson<JinjaTemplate[]>('/admin/jinja-templates'),
  })

  const upsert = useMutation({
    mutationFn: ({ key, culture, body }: { key: string; culture: string; body: string }) =>
      apiFetchJson<JinjaTemplate>(`/admin/jinja-templates/${encodeURIComponent(key)}/${encodeURIComponent(culture)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })

  const remove = useMutation({
    mutationFn: ({ key, culture }: { key: string; culture: string }) =>
      apiFetchVoid(`/admin/jinja-templates/${encodeURIComponent(key)}/${encodeURIComponent(culture)}`, {
        method: 'DELETE',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  })

  const preview = useMutation({
    mutationFn: ({ body, ctx }: { body: string; ctx: unknown }) =>
      apiFetchJson<{ rendered: string }>('/admin/jinja-templates/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body, ctx }),
      }),
  })

  return { templates, upsert, remove, preview }
}
