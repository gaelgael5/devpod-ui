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
  /** Utilisateur SSH (partie `<user>@` de l'adresse). Vide si l'adresse est nue. */
  user?: string
  vmid: string
  /** Non vide = VM partagée-vers ce workspace depuis le workspace nommé (bloc en
   *  lecture seule : accès SSH sans contrôle du cycle de vie). */
  sharedFrom?: string
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
    // Une machine supprimee disparait de PARTOUT. Elle est listee a trois
    // endroits — la carte du workspace, l'administration des hosts, la page des
    // sessions — et n'invalider que la premiere la laissait visible ailleurs,
    // avec des actions qui echouaient sur une machine inexistante.
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['me', 'workspaces', wsName, 'test-hosts'] })
      qc.invalidateQueries({ queryKey: ['admin', 'hosts'] })
      qc.invalidateQueries({ queryKey: ['sessions'] })
    },
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

/** Édite les paramètres de connexion mémorisés d'une machine de test (host/username/
 *  password). `password` omis = secret inchangé ; fourni = remplace le mot de passe root. */
export function useUpdateTestHostConn(wsName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: { hostName: string; username: string; host: string; password?: string }) => {
      const body: Record<string, string> = { username: args.username, host: args.host }
      if (args.password !== undefined) body.password = args.password
      return apiFetchJson<TestHost>(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-vm/${encodeURIComponent(args.hostName)}/connection`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
    },
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['me', 'workspaces', wsName, 'test-hosts'] }),
  })
}

/** Révèle le mot de passe root d'une machine de test, gardé par le PIN vault.
 *  Valeur éphémère, jamais mise en cache de query. */
export function useRevealTestHostRootPassword(wsName: string) {
  return useMutation({
    mutationFn: (args: { hostName: string; pin: string }) =>
      apiFetchJson<{ value: string }>(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-vm/${encodeURIComponent(args.hostName)}/root-password/reveal`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: args.pin }),
        },
      ),
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

interface CreateJobStart { job_id: string }
interface CreateJobProgress { status: 'running' | 'ok' | 'failed'; log: string }

const POLL_INTERVAL_MS = 1500
// Le provisioning tourne côté serveur indépendamment : quelques polls ratés
// (blip réseau, mise en arrière-plan mobile) ne doivent pas faire abandonner —
// la machine est ajoutée quoi qu'il arrive. On n'abandonne qu'après N échecs consécutifs.
const MAX_CONSECUTIVE_POLL_FAILURES = 6

/**
 * Crée une VM de test. Le backend provisionne EN TÂCHE DE FOND (202 + job_id) et
 * l'IHM poll la progression : perdre la connexion (navigation, 4G, arrière-plan)
 * n'interrompt plus la création — la machine finit toujours par être enregistrée.
 */
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
      const { job_id } = await apiFetchJson<CreateJobStart>(`/me/workspaces/${wsName}/test-vm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hypervisor, vmid }),
      })
      let failures = 0
      for (;;) {
        await new Promise(r => setTimeout(r, POLL_INTERVAL_MS))
        let prog: CreateJobProgress
        try {
          prog = await apiFetchJson<CreateJobProgress>(
            `/me/workspaces/${wsName}/test-vm/create/${job_id}`,
          )
          failures = 0
        } catch (e) {
          if (++failures >= MAX_CONSECUTIVE_POLL_FAILURES) throw e
          continue
        }
        setState(s => ({ ...s, logs: prog.log }))
        if (prog.status !== 'running') {
          setState(s => ({
            ...s,
            logs: prog.log,
            running: false,
            done: true,
            error: prog.status === 'failed' ? 'La création a échoué (voir le journal).' : null,
          }))
          break
        }
      }
      qc.invalidateQueries({ queryKey: ['me', 'workspaces', wsName, 'test-hosts'] })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setState(s => ({ ...s, error: msg, running: false, done: true }))
    }
  }, [qc])

  return { ...state, execute, reset }
}

export interface HostStack {
  name: string
  status: string
  configFiles: string
}

export interface HostContainer {
  name: string
  image: string
  state: string
  status: string
}

export interface HostDocker {
  stacks: HostStack[]
  containers: HostContainer[]
}

/** État docker LIVE de la machine : stacks compose + conteneurs hors compose. */
export function useHostDocker(wsName: string, hostName: string, enabled: boolean) {
  return useQuery<HostDocker>({
    queryKey: ['me', 'workspaces', wsName, 'test-hosts', hostName, 'stacks'],
    queryFn: () =>
      apiFetchJson<HostDocker>(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-hosts/${encodeURIComponent(hostName)}/stacks`,
      ),
    enabled,
    staleTime: 10_000,
    refetchInterval: 15_000,
  })
}

/** Workspaces à qui une VM de test (possédée par wsName) est partagée. */
export function useTestHostShares(wsName: string, hostName: string, enabled: boolean) {
  return useQuery<string[]>({
    queryKey: ['me', 'workspaces', wsName, 'test-hosts', hostName, 'shares'],
    queryFn: async () => {
      const r = await apiFetchJson<{ shared: string[] }>(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-hosts/${encodeURIComponent(hostName)}/shares`,
      )
      return r.shared
    },
    enabled,
    staleTime: 15_000,
  })
}

/** Réconcilie l'ensemble des workspaces partagés (cases cochées de la fenêtre). */
export function useSetTestHostShares(wsName: string, hostName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (workspaces: string[]) => {
      const r = await apiFetchJson<{ shared: string[] }>(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-hosts/${encodeURIComponent(hostName)}/shares`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspaces }),
        },
      )
      return r.shared
    },
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ['me', 'workspaces', wsName, 'test-hosts', hostName, 'shares'],
      })
      // Le partage crée un message agent PENDING côté cible → rafraîchir les compteurs.
      qc.invalidateQueries({ queryKey: ['agent-messages'] })
    },
  })
}

export interface TestHostLink {
  key: string
  url: string
}

/** Liens (clé → URL) enregistrés pour un serveur de test (menu ⋮ du host). */
export function useTestHostLinks(wsName: string, hostName: string) {
  return useQuery<TestHostLink[]>({
    queryKey: ['me', 'workspaces', wsName, 'test-hosts', hostName, 'links'],
    queryFn: () =>
      apiFetchJson<TestHostLink[]>(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-hosts/${encodeURIComponent(hostName)}/links`,
      ),
    staleTime: 30_000,
  })
}

export function useSaveTestHostLink(wsName: string, hostName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (link: TestHostLink) =>
      apiFetchJson<TestHostLink>(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-hosts/${encodeURIComponent(hostName)}/links`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(link),
        },
      ),
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ['me', 'workspaces', wsName, 'test-hosts', hostName, 'links'],
      }),
  })
}

export function useDeleteTestHostLink(wsName: string, hostName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (key: string) => {
      const res = await apiFetch(
        `/me/workspaces/${encodeURIComponent(wsName)}/test-hosts/${encodeURIComponent(hostName)}/links/${encodeURIComponent(key)}`,
        { method: 'DELETE' },
      )
      if (!res.ok) throw new Error((await res.text().catch(() => '')) || `HTTP ${res.status}`)
    },
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ['me', 'workspaces', wsName, 'test-hosts', hostName, 'links'],
      }),
  })
}
