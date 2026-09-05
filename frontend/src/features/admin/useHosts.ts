import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiFetch, apiFetchJson, apiFetchVoid } from '@/shared/api/client'

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
  // Cert client mTLS (docker-tls) : slug d'une entrée tls-* du gestionnaire de
  // certificats. Vide = répertoire partagé du portail.
  docker_cert_slug?: string
  // Destination : workspaces, tests, portail (machine du portail), ou
  // ressources (service partagé permanent, sans workspace propriétaire — spec 33).
  usage?: 'workspaces' | 'tests' | 'portail' | 'ressources' | 'autres'
  // Profil avec lequel la machine a été montée. Lecture seule : posé au
  // provisionnement, jamais saisi ici.
  profile_slug?: string
  // Combien de workspaces la machine tient sans planter. `null` = non
  // renseigné, ce qui n'est ni zéro ni l'infini.
  capacity_workspaces?: number | null
  // La machine peut-elle accueillir les workspaces d'offres mutualisées ?
  accepts_mutualise?: boolean
  // Hyperviseur qui a monté la machine. Provenance, pas contrainte : posée au
  // provisionnement, jamais saisie ici. Vide = inconnue (machine enrôlée à la
  // main, ou antérieure à la colonne) — ni une erreur, ni un défaut.
  hypervisor?: string
  // Plafond mémoire par workspace (syntaxe Docker). Vide = non renseigné :
  // aucun bornage. Le backend refuse (422) une demande au-dessus ; ce champ
  // permet de le signaler avant l'envoi.
  max_memory?: string
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
  docker_cert_slug?: string
  ssh_cert_slug?: string
  usage?: 'workspaces' | 'tests' | 'portail' | 'ressources' | 'autres'
  // Champ ABSENT = le serveur préserve la valeur ; `null` = « non renseigné ».
  capacity_workspaces?: number | null
  accepts_mutualise?: boolean
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
      apiFetchVoid(`/admin/hosts/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'hosts'] }),
    onError: (err: Error) => toast.error(err.message),
  })
}

// Révélation du mot de passe console (gardée par PIN — enabler 6e3d5f3a).
// Pas d'invalidation de cache : la valeur est éphémère, jamais stockée en query.
export function useRevealCiPassword() {
  return useMutation({
    mutationFn: ({ name, pin }: { name: string; pin: string }) =>
      apiFetchJson<{ value: string }>(
        `/admin/hosts/${encodeURIComponent(name)}/ci-password/reveal`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin }),
        },
      ),
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
  const controllerRef = useRef<AbortController | null>(null)
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null)

  const reset = useCallback(() => {
    setState({ logs: '', running: false, done: false, error: null })
  }, [])

  const execute = useCallback(async (hypervisorName: string, vmid: string) => {
    // Un execute() concurrent (retry sans fermer le dialog) ne doit pas laisser
    // l'ancien stream ouvert (bug 020).
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setState({ logs: '', running: true, done: false, error: null })
    try {
      const res = await apiFetch(`/admin/hypervisors/${encodeURIComponent(hypervisorName)}/execute-destroy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vmid }),
        signal: controller.signal,
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }
      const reader = res.body!.getReader()
      readerRef.current = reader
      const decoder = new TextDecoder()
      let accum = ''
      while (true) {
        const { done: streamDone, value } = await reader.read()
        if (streamDone) break
        accum += decoder.decode(value, { stream: true })
        const snap = accum
        setState(s => ({ ...s, logs: snap }))
      }
      readerRef.current = null
      setState(s => ({ ...s, logs: accum, running: false, done: true }))
    } catch (e) {
      readerRef.current = null
      // Annulé (unmount ou nouvel execute()) : le hook est détaché, pas d'update d'état.
      if (controller.signal.aborted) return
      const msg = e instanceof Error ? e.message : String(e)
      setState(s => ({ ...s, error: msg, running: false, done: true }))
    }
  }, [])

  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
      readerRef.current?.cancel().catch(() => {})
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

// ─── Groupement des hosts de test par workspace ─────────────────────────────

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

// ─── Vue « parc » : filtres, tris et pagination SERVEUR ───────────────────────

/** Une ligne de la vue parc : nature, propriétaire, charge. `disk_used_pct`
 * null = machine JAMAIS sondée — un inconnu, pas 0 %. */
export interface LigneParc {
  name: string
  usage: string
  accepts_mutualise: boolean
  /** null sur une mutualisée : deux natures, deux rendus. */
  owner_login: string | null
  workspaces: number
  disk_used_pct: number | null
  mem_used_bytes: number | null
  mem_total_bytes: number | null
  hypervisor: string
  capacity_workspaces: number | null
}

export interface PageParc {
  total: number
  page: number
  page_size: number
  proprietaires: string[]
  hosts: LigneParc[]
}

export type TriParc = 'nom' | 'workspaces' | 'disque' | 'memoire'

/** Valeur du filtre propriétaire qui sélectionne le POOL (décidé 31/08). */
export const FILTRE_MUTUALISE = '__mutualise__'

export interface ParcParams {
  q: string
  owner: string
  tri: TriParc
  descendant: boolean
  page: number
}

export function useParcHosts(params: ParcParams) {
  const qs = new URLSearchParams({
    q: params.q,
    owner: params.owner,
    tri: params.tri,
    descendant: String(params.descendant),
    page: String(params.page),
    page_size: '25',
    // L'écran des hôtes de workspaces : tests/ressources/autres ont leurs sections.
    hors_usages: 'tests,ressources,autres',
  })
  return useQuery<PageParc>({
    queryKey: ['admin', 'hosts', 'parc', params],
    queryFn: () => apiFetchJson<PageParc>(`/admin/hosts/parc?${qs.toString()}`),
    placeholderData: (prev) => prev,
  })
}
