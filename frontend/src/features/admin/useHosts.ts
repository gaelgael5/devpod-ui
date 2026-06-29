import { useCallback, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
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
  // Destination : workspaces (sélectionnable à la création) ou tests.
  usage?: 'workspaces' | 'tests'
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

export interface TestHostInfo {
  owner_login: string
  workspace_name: string
  alias: string
}

export function useTestHostInfo(name: string, enabled: boolean) {
  return useQuery<TestHostInfo | null>({
    queryKey: ['admin', 'hosts', name, 'test-info'],
    queryFn: () =>
      apiFetchJson<TestHostInfo | null>(
        `/admin/hosts/${encodeURIComponent(name)}/test-info`,
      ),
    enabled,
    staleTime: 30 * 1000,
  })
}

export interface HostDeployment {
  id: string
  status: string
  template_id: string
  template_name: string
  template_version: string
  host_ports: number[]
  last_error: string | null
  created_at: string | null
}

export function useHostDeployments(name: string, enabled: boolean) {
  return useQuery<HostDeployment[]>({
    queryKey: ['admin', 'hosts', name, 'deployments'],
    queryFn: () =>
      apiFetchJson<HostDeployment[]>(
        `/admin/hosts/${encodeURIComponent(name)}/deployments`,
      ),
    enabled,
    staleTime: 15 * 1000,
    refetchInterval: 15 * 1000,
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

// ─── Groupement des hosts de test par workspace ───────────────────────────────

export interface TestHostEntry {
  host: HostConfig
  info: TestHostInfo | null
  deployments: HostDeployment[]
  loading: boolean
}

export interface WorkspaceTestGroup {
  workspace_name: string
  entries: TestHostEntry[]
}

export interface UserTestGroup {
  owner_login: string
  workspaces: WorkspaceTestGroup[]
}

export function useTestHostsSummary(hosts: HostConfig[]): UserTestGroup[] {
  const testHosts = hosts.filter((h) => h.usage === 'tests')

  const infoResults = useQueries({
    queries: testHosts.map((h) => ({
      queryKey: ['admin', 'hosts', h.name, 'test-info'] as const,
      queryFn: () => apiFetchJson<TestHostInfo | null>(`/admin/hosts/${encodeURIComponent(h.name)}/test-info`),
      staleTime: 30_000,
    })),
  })

  const depsResults = useQueries({
    queries: testHosts.map((h) => ({
      queryKey: ['admin', 'hosts', h.name, 'deployments'] as const,
      queryFn: () => apiFetchJson<HostDeployment[]>(`/admin/hosts/${encodeURIComponent(h.name)}/deployments`),
      staleTime: 15_000,
      refetchInterval: 15_000,
    })),
  })

  // user → workspace → entries
  const userMap = new Map<string, Map<string, TestHostEntry[]>>()

  testHosts.forEach((h, i) => {
    const info = infoResults[i]?.data ?? null
    const deps = depsResults[i]?.data ?? []
    const loading = (infoResults[i]?.isLoading ?? true) || (depsResults[i]?.isLoading ?? true)
    const userKey = info?.owner_login ?? '?'
    const wsKey = info?.workspace_name ?? h.name

    if (!userMap.has(userKey)) userMap.set(userKey, new Map())
    const wsMap = userMap.get(userKey)!
    if (!wsMap.has(wsKey)) wsMap.set(wsKey, [])
    wsMap.get(wsKey)!.push({ host: h, info, deployments: deps, loading })
  })

  return [...userMap.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([owner_login, wsMap]) => ({
      owner_login,
      workspaces: [...wsMap.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([workspace_name, entries]) => ({ workspace_name, entries })),
    }))
}
