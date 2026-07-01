import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'
import type { ScriptSpec } from '@/features/admin/useProxmoxScript'

export interface TestHypervisor {
  name: string
  type: string
  label: string
}

export interface TestHost {
  alias: string
  name: string
  ip: string
  vmid: string
}

/** Machines de test attachées à un workspace (pour le menu SSH test). */
export function useTestHosts(wsName: string, enabled: boolean) {
  return useQuery<TestHost[]>({
    queryKey: ['me', 'workspaces', wsName, 'test-hosts'],
    queryFn: () =>
      apiFetchJson<TestHost[]>(`/me/workspaces/${encodeURIComponent(wsName)}/test-hosts`),
    enabled,
    staleTime: 30_000,
  })
}

/** Supprime une machine de test (détruit la VM + nettoyage). */
export function useDeleteTestHost(wsName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (hostName: string) => {
      const res = await apiFetch(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-vm/${encodeURIComponent(hostName)}`,
        { method: 'DELETE' },
      )
      if (!res.ok) throw new Error((await res.text().catch(() => '')) || `HTTP ${res.status}`)
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['me', 'workspaces', wsName, 'test-hosts'] }),
  })
}

/** Re-résout l'IP DHCP d'une machine de test via DNS (nom + domaine local). */
export function useResolveTestHostIp(wsName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (hostName: string) =>
      apiFetchJson<{ ip: string; fqdn: string }>(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-vm/${encodeURIComponent(hostName)}/resolve-ip`,
        { method: 'POST' },
      ),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['me', 'workspaces', wsName, 'test-hosts'] }),
  })
}

export function useTestHypervisors(enabled: boolean) {
  return useQuery<TestHypervisor[]>({
    queryKey: ['me', 'test-hypervisors'],
    queryFn: () => apiFetchJson<TestHypervisor[]>('/me/test-hypervisors'),
    enabled,
    staleTime: 60_000,
  })
}

export function useTestVmScript(hypervisor: string | null) {
  return useQuery<ScriptSpec>({
    queryKey: ['me', 'test-hypervisors', hypervisor, 'script'],
    queryFn: () => apiFetchJson<ScriptSpec>(`/me/test-hypervisors/${hypervisor}/script`),
    enabled: hypervisor != null,
    staleTime: 30_000,
    retry: false,
  })
}

export interface CreateTestVmState {
  logs: string
  running: boolean
  done: boolean
  error: string | null
}

/** Crée une VM de test en streamant les logs (mêmes mécaniques que useDestroyVm). */
export function useCreateTestVm() {
  const qc = useQueryClient()
  const [state, setState] = useState<CreateTestVmState>({
    logs: '', running: false, done: false, error: null,
  })

  const reset = useCallback(() => {
    setState({ logs: '', running: false, done: false, error: null })
  }, [])

  const execute = useCallback(async (wsName: string, hypervisor: string, vmid: string) => {
    setState({ logs: '', running: true, done: false, error: null })
    try {
      const res = await apiFetch(`/me/workspaces/${wsName}/test-vm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hypervisor, vmid }),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let accum = ''
      while (true) {
        const { done: streamDone, value } = await reader.read()
        if (streamDone) break
        accum += decoder.decode(value, { stream: true })
        const snap = accum
        setState(s => ({ ...s, logs: snap }))
      }
      setState(s => ({ ...s, logs: accum, running: false, done: true }))
      qc.invalidateQueries({ queryKey: ['me', 'workspaces', wsName, 'test-hosts'] })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setState(s => ({ ...s, error: msg, running: false, done: true }))
    }
  }, [qc])

  return { ...state, execute, reset }
}
