import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
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
}

function toSourceSpec(entry: SourceEntry): SourceSpec {
  return { url: entry.url, branch: entry.branch, git_credential: entry.credential }
}

export function useWorkspaceOps() {
  const qc = useQueryClient()

  const createWorkspace = useMutation({
    mutationFn: async ({ name, sources, host, recipes, generateSshKey, profile }: CreateInput) => {
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

  const deleteWorkspace = useMutation({
    mutationFn: async (name: string) => {
      await apiFetchJson(`/me/workspaces/${name}/delete`, { method: 'POST' })
      await apiFetch(`/me/workspaces/${name}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  return { createWorkspace, stopWorkspace, deleteWorkspace }
}
