/**
 * Templates de création de workspace (galerie préparée par l'admin).
 *
 * Côté utilisateur : la galerie publiée + la création « nom + repo, le preset
 * fait le reste ». Côté admin : le CRUD complet. La précédence du merge vit au
 * backend (explicite > template > défaut) — le front ne merge jamais.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface WorkspaceTemplateSpec {
  branch: string
  recipes: string[]
  start_recipes: string[]
  init_recipes: string[]
  recipe_volumes: string[]
  default_start: string
  agents: string[]
  profile: { scope: 'shared' | 'user'; slug: string } | null
  memory_limit: string
  ssh_key: boolean
  ide: string
  env: Record<string, string>
}

export interface WorkspaceTemplate {
  slug: string
  label: string
  description: string
  published: boolean
  spec: WorkspaceTemplateSpec
}

export const SPEC_VIDE: WorkspaceTemplateSpec = {
  branch: '',
  recipes: [],
  start_recipes: [],
  init_recipes: [],
  recipe_volumes: [],
  default_start: '',
  agents: [],
  profile: null,
  memory_limit: '',
  ssh_key: false,
  ide: '',
  env: {},
}

const QK_GALERIE = ['workspace-templates']
const QK_ADMIN = ['admin', 'workspace-templates']

/** La galerie publiée — ce que le dialogue de création propose. */
export function useWorkspaceTemplates() {
  return useQuery({
    queryKey: QK_GALERIE,
    queryFn: () => apiFetchJson<WorkspaceTemplate[]>('/workspace-templates'),
    staleTime: 30_000,
  })
}

export function useCreateFromTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { template: string; name: string; source: string }) =>
      apiFetchJson('/me/workspaces/from-template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  })
}

// ─── Admin ────────────────────────────────────────────────────────────────────

export function useAdminWorkspaceTemplates() {
  return useQuery({
    queryKey: QK_ADMIN,
    queryFn: () => apiFetchJson<WorkspaceTemplate[]>('/admin/workspace-templates'),
  })
}

export function useSaveWorkspaceTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (template: WorkspaceTemplate) =>
      apiFetchJson<WorkspaceTemplate>(
        `/admin/workspace-templates/${encodeURIComponent(template.slug)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            label: template.label,
            description: template.description,
            published: template.published,
            spec: template.spec,
          }),
        },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QK_ADMIN })
      queryClient.invalidateQueries({ queryKey: QK_GALERIE })
    },
  })
}

export function useDeleteWorkspaceTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (slug: string) => {
      // 204 sans corps : apiFetchJson tenterait un res.json() sur du vide.
      const res = await apiFetch(`/admin/workspace-templates/${encodeURIComponent(slug)}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error(`suppression refusée (${res.status})`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QK_ADMIN })
      queryClient.invalidateQueries({ queryKey: QK_GALERIE })
    },
  })
}
