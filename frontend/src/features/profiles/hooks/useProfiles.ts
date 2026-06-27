import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  createProfile,
  createSharedProfile,
  deleteProfile,
  deleteSharedProfile,
  forkProfile,
  getProfile,
  listProfiles,
  updateProfile,
  updateSharedProfile,
} from '../api/profiles'
import type { ProfileBody, Scope } from '../api/profiles'

const QK = ['profiles'] as const

export function useProfiles() {
  return useQuery({
    queryKey: QK,
    queryFn: listProfiles,
    staleTime: 30_000,
  })
}

export function useProfile(scope: Scope, slug?: string) {
  return useQuery({
    queryKey: [...QK, scope, slug],
    queryFn: () => getProfile(scope, slug!),
    enabled: Boolean(slug),
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ slug, body }: { slug?: string; body: ProfileBody }) =>
      slug ? updateProfile(slug, body) : createProfile(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useDeleteProfile() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: deleteProfile,
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useForkProfile() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: forkProfile,
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message),
  })
}

// ── Admin ────────────────────────────────────────────────────────────────────

export function useSaveSharedProfile() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({ slug, body }: { slug?: string; body: ProfileBody }) =>
      slug ? updateSharedProfile(slug, body) : createSharedProfile(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message),
  })
}

export function useDeleteSharedProfile() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: deleteSharedProfile,
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
    onError: (err: Error) => toast.error(err.message),
  })
}
