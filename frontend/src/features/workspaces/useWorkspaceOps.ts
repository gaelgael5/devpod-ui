import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetch, apiFetchJson } from '@/shared/api/client'
import type { WorkspaceSpec } from './types'

interface CreateInput {
  name: string
  source: string
  host: string
  recipes: string[]
}

export function useWorkspaceOps() {
  const qc = useQueryClient()

  const createWorkspace = useMutation({
    mutationFn: async ({ name, source, host, recipes }: CreateInput) => {
      const spec: WorkspaceSpec = { name, source, host, recipes, env: {} }
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
        body: JSON.stringify({ source, host, recipes }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err: Error) => {
      toast.error(err.message)
    },
  })

  const stopWorkspace = useMutation({
    mutationFn: (name: string) =>
      apiFetchJson(`/me/workspaces/${name}/stop`, { method: 'POST' }),
    onSuccess: (_data, name) => {
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
