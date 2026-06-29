import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { apiFetch, apiFetchJson } from '@/shared/api/client'
import type { SourceSpec, WorkspaceSpec, WorkspaceStatus } from './types'

export interface SourceEntry {
  url: string
  branch: string
  credential: string
}

interface CreateInput {
  name: string
  sources: SourceEntry[]
  host: string
  recipes: string[]
  generateSshKey?: boolean
  profile?: { scope: 'shared' | 'user'; slug: string }
  startRecipes?: string[]
  defaultStart?: string
  volumeRecipes?: string[]
  initRecipes?: string[]
}

function toSourceSpec(entry: SourceEntry): SourceSpec {
  return { url: entry.url, branch: entry.branch, git_credential: entry.credential }
}

export function useWorkspaceOps() {
  const qc = useQueryClient()
  const { t } = useTranslation()

  const createWorkspace = useMutation({
    mutationFn: async ({ name, sources, host, recipes, generateSshKey, profile, startRecipes, defaultStart, volumeRecipes, initRecipes }: CreateInput) => {
      const primary = sources[0] ?? { url: '', branch: '', credential: '' }
      const extra = sources.slice(1).map(toSourceSpec)

      const spec: WorkspaceSpec = {
        name,
        source: primary.url,
        branch: primary.branch,
        git_credential: primary.credential,
        host,
        recipes,
        env: {},
        extra_sources: extra,
        ssh_key: generateSshKey ?? false,
        profile: profile ?? null,
        start_recipes: startRecipes ?? [],
        default_start: defaultStart ?? '',
        recipe_volumes: volumeRecipes ?? [],
        init_recipes: initRecipes ?? [],
      }
      // Add to config (ignore 409 — already exists)
      const addRes = await apiFetch('/me/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(spec),
      })
      if (!addRes.ok && addRes.status !== 409) {
        const text = await addRes.text().catch(() => '')
        throw new Error(text || addRes.statusText)
      }
      // Start the workspace
      await apiFetchJson(`/me/workspaces/${name}/up`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: primary.url,
          branch: primary.branch,
          git_credential: primary.credential,
          host,
          recipes,
          extra_sources: extra,
          generate_ssh_key: generateSshKey ?? false,
          profile: profile ?? null,
          recipe_volumes: volumeRecipes ?? [],
        }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err: Error) => {
      toast.error(err.message)
    },
  })

  const stopWorkspace = useMutation<WorkspaceStatus, Error, string>({
    mutationFn: (name: string) =>
      apiFetchJson<WorkspaceStatus>(`/me/workspaces/${name}/stop`, { method: 'POST' }),
    onSuccess: (_data: WorkspaceStatus, name: string) => {
      qc.invalidateQueries({ queryKey: ['workspace-status', name] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const deleteWorkspace = useMutation<
    { deleted: boolean; recovery_branch: string | null },
    Error,
    { name: string; shelve?: boolean }
  >({
    mutationFn: async ({ name, shelve = true }) => {
      const url = `/me/workspaces/${name}/delete?shelve=${shelve}`
      const result = await apiFetchJson<{
        deleted: boolean
        recovery_branch: string | null
      }>(url, { method: 'POST' })
      await apiFetch(`/me/workspaces/${name}`, { method: 'DELETE' })
      return result
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      if (data.recovery_branch) {
        toast.success(t('workspaces.confirm.recoverySaved', { branch: data.recovery_branch }))
      }
    },
    onError: (err: Error) => {
      let msg = err.message
      try {
        const parsed: unknown = JSON.parse(err.message)
        if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
          msg = String((parsed as { detail: unknown }).detail)
        }
      } catch {
        // message n'est pas du JSON, on l'utilise tel quel
      }
      toast.error(msg)
    },
  })

  const recreateWorkspace = useMutation<{ ws_id: string; status: string }, Error, string>({
    mutationFn: (name: string) =>
      apiFetchJson<{ ws_id: string; status: string }>(`/me/workspaces/${name}/recreate`, {
        method: 'POST',
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  // Démarre un workspace existant (stopped/failed) sans passer par POST /me/workspaces
  // qui retournerait 409 — la config est déjà enregistrée.
  const startWorkspace = useMutation({
    mutationFn: (spec: WorkspaceSpec) => {
      const extra = spec.extra_sources.map((s) => ({
        url: s.url,
        branch: s.branch,
        git_credential: s.git_credential,
      }))
      return apiFetchJson(`/me/workspaces/${spec.name}/up`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: spec.source,
          branch: spec.branch,
          git_credential: spec.git_credential,
          host: spec.host,
          recipes: spec.recipes,
          extra_sources: extra,
          generate_ssh_key: spec.ssh_key,
          profile: spec.profile,
          recipe_volumes: spec.recipe_volumes ?? [],
        }),
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workspaces'] }),
    onError: (err: Error) => toast.error(err.message),
  })

  return { createWorkspace, startWorkspace, stopWorkspace, deleteWorkspace, recreateWorkspace }
}
