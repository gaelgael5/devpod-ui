import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

export type VaultStatus = 'setup_required' | 'locked' | 'unlocked'

export interface VaultKey {
  identifier: string
  url: string
  description: string
  created_at: string
}

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`)
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

export const vaultQueryKeys = {
  status: () => ['vault', 'status'] as const,
  keys: () => ['vault', 'keys'] as const,
}

export function useVaultStatus() {
  return useQuery({
    queryKey: vaultQueryKeys.status(),
    queryFn: () => apiFetch<{ status: VaultStatus }>('/vault/status'),
  })
}

export function useVaultKeys() {
  return useQuery({
    queryKey: vaultQueryKeys.keys(),
    queryFn: () => apiFetch<VaultKey[]>('/vault/keys'),
  })
}

export function usePinSetup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (pin: string) =>
      apiFetch<{ recovery_code: string }>('/vault/pin/setup', {
        method: 'POST',
        body: JSON.stringify({ pin }),
      }),
    onSuccess: () => qc.setQueryData(vaultQueryKeys.status(), { status: 'unlocked' }),
  })
}

export function usePinUnlock() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (pin: string) =>
      apiFetch<{ status: string }>('/vault/pin/unlock', {
        method: 'POST',
        body: JSON.stringify({ pin }),
      }),
    onSuccess: () => qc.setQueryData(vaultQueryKeys.status(), { status: 'unlocked' }),
  })
}

export function usePinRecover() {
  return useMutation({
    mutationFn: (body: { recovery_code: string; new_pin: string }) =>
      apiFetch<{ recovery_code: string }>('/vault/pin/recover', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  })
}

export function useAddVaultKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      identifier: string
      token: string
      url: string
      description: string
    }) =>
      apiFetch<{ identifier: string }>('/vault/keys', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: vaultQueryKeys.keys() }),
  })
}

export function useDeleteVaultKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (identifier: string) =>
      apiFetch<void>(`/vault/keys/${identifier}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: vaultQueryKeys.keys() }),
  })
}

export function useTestVaultKey() {
  return useMutation({
    mutationFn: (identifier: string) =>
      apiFetch<{ api_key_id: string; wallet_id: string; permissions: number }>(
        `/vault/keys/${identifier}/test`,
        { method: 'POST' }
      ),
  })
}
