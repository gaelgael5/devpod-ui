import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface HostConfig {
  name: string
  type: 'docker-tls' | 'ssh'
  default?: boolean
  docker_host?: string
  address?: string
  proxmox_node?: string
  vmid?: string
  // Références harpo_* (lecture seule — jamais de secret brut)
  ci_password_secret_slug?: string
  host_cert_slug?: string
}

export interface HostCreatePayload {
  name: string
  type: 'docker-tls' | 'ssh'
  default?: boolean
  docker_host?: string
  address?: string
  proxmox_node?: string
  vmid?: string
  ci_password?: string
}

export function useHosts() {
  return useQuery<HostConfig[]>({
    queryKey: ['admin', 'hosts'],
    queryFn: () => apiFetchJson<HostConfig[]>('/admin/hosts'),
    staleTime: 2 * 60 * 1000,
  })
}

export function useAddHost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: HostCreatePayload) =>
      apiFetchJson<HostConfig>('/admin/hosts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useUpdateHost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: HostCreatePayload) =>
      apiFetchJson<HostConfig>(`/admin/hosts/${encodeURIComponent(payload.name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useDeleteHost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch(`/admin/hosts/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useHostCert(name: string, enabled: boolean) {
  return useQuery<Record<string, string>>({
    queryKey: ['admin', 'hosts', name, 'cert'],
    queryFn: () => apiFetchJson<Record<string, string>>(`/admin/hosts/${encodeURIComponent(name)}/cert`),
    enabled,
    retry: false,
  })
}

export interface ProxmoxNodeSummary {
  name: string
  address: string
}

export function useProxmoxNodes() {
  return useQuery<ProxmoxNodeSummary[]>({
    queryKey: ['admin', 'proxmox-nodes'],
    queryFn: async () => {
      const cfg = await apiFetchJson<{ hypervisors?: ProxmoxNodeSummary[] }>('/admin/config')
      return cfg.hypervisors ?? []
    },
    staleTime: 5 * 60 * 1000,
  })
}

export interface DestroyVmState {
  logs: string
  running: boolean
  done: boolean
  error: string | null
}

export function useDestroyVm() {
  const [state, setState] = useState<DestroyVmState>({
    logs: '',
    running: false,
    done: false,
    error: null,
  })

  const reset = useCallback(() => {
    setState({ logs: '', running: false, done: false, error: null })
  }, [])

  const execute = useCallback(async (hypervisorName: string, vmid: string) => {
    setState({ logs: '', running: true, done: false, error: null })
    try {
      const res = await apiFetch(`/admin/hypervisors/${encodeURIComponent(hypervisorName)}/execute-destroy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vmid }),
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
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setState(s => ({ ...s, error: msg, running: false, done: true }))
    }
  }, [])

  return { ...state, execute, reset }
}

export interface HostWorkspaceEntry {
  name: string
  status: string
}

export interface HostUserWorkspaces {
  login: string
  workspaces: HostWorkspaceEntry[]
}

export function useHostWorkspaces(name: string) {
  return useQuery<HostUserWorkspaces[]>({
    queryKey: ['admin', 'hosts', name, 'workspaces'],
    queryFn: () =>
      apiFetchJson<HostUserWorkspaces[]>(
        `/admin/hosts/${encodeURIComponent(name)}/workspaces`,
      ),
    staleTime: 10 * 1000,
    refetchInterval: 10 * 1000,
  })
}

export interface BootstrapSshPayload {
  address: string
  proxmox_node: string
}

export interface BootstrapSshResult {
  public_key: string
  address: string
  host_cert_slug: string
}

export function useBootstrapSsh() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: BootstrapSshPayload }) =>
      apiFetchJson<BootstrapSshResult>(
        `/admin/hosts/${encodeURIComponent(name)}/bootstrap-ssh`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}
