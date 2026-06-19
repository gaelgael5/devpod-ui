import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type VaultStatus = 'setup_required' | 'locked' | 'unlocked'

export interface VaultKey {
  identifier: string
  url: string
  description: string
  created_at: string
}

export const vaultQueryKeys = {
  status: () => ['vault', 'status'] as const,
  keys: () => ['vault', 'keys'] as const,
}

export function useVaultStatus() {
  return useQuery({
    queryKey: vaultQueryKeys.status(),
    queryFn: () => apiFetchJson<{ status: VaultStatus }>('/vault/status'),
  })
}

export function useVaultKeys() {
  return useQuery({
    queryKey: vaultQueryKeys.keys(),
    queryFn: () => apiFetchJson<VaultKey[]>('/vault/keys'),
  })
}

export function usePinSetup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (pin: string) =>
      apiFetchJson<{ recovery_code: string }>('/vault/pin/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
      }),
    onSuccess: () => qc.setQueryData(vaultQueryKeys.status(), { status: 'unlocked' }),
  })
}

export function usePinUnlock() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (pin: string) =>
      apiFetchJson<{ status: string }>('/vault/pin/unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
      }),
    onSuccess: () => qc.setQueryData(vaultQueryKeys.status(), { status: 'unlocked' }),
  })
}

export function usePinRecover() {
  return useMutation({
    mutationFn: (body: { recovery_code: string; new_pin: string }) =>
      apiFetchJson<{ recovery_code: string }>('/vault/pin/recover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
  })
}

export function useAddVaultKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { identifier: string; token: string; url: string; description: string }) =>
      apiFetchJson<{ identifier: string }>('/vault/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: vaultQueryKeys.keys() }),
  })
}

export function useDeleteVaultKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (identifier: string) =>
      apiFetch(`/vault/keys/${encodeURIComponent(identifier)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: vaultQueryKeys.keys() }),
  })
}

export function useTestVaultKey() {
  return useMutation({
    mutationFn: (identifier: string) =>
      apiFetchJson<{ api_key_id: string; wallet_id: string; permissions: number }>(
        `/vault/keys/${encodeURIComponent(identifier)}/test`,
        { method: 'POST' },
      ),
  })
}
