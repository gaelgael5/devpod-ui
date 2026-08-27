import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'
import type { HypervisorVariable } from './useAdminHypervisorTypes'

/**
 * Profil de host : ce qu'un forfait provisionne.
 *
 * Trois niveaux, chacun avec sa responsabilite — le type d'hyperviseur DECLARE
 * les variables, le profil de machine fige les parametres de creation, le
 * profil de host VALUE ces variables. `capacity_workspaces` vit ici : le profil
 * de machine sait construire la VM, il ne sait pas combien de workspaces elle
 * tient sans planter.
 */
export interface HostProfile {
  slug: string
  label: string
  /** Slug du profil de machine — c'est lui qui porte le type d'hyperviseur. */
  machine_profile: string
  /** Slug de variable → valeur, en texte : la declaration porte le type. */
  variables: Record<string, string>
}

export function profilHostVide(machineProfile: string): HostProfile {
  return { slug: '', label: '', machine_profile: machineProfile, variables: {} }
}

export function useHostProfiles() {
  return useQuery({
    queryKey: ['admin', 'host-profiles'],
    queryFn: () => apiFetchJson<HostProfile[]>('/admin/host-profiles'),
  })
}

/**
 * Variables a renseigner pour un profil de machine donne.
 *
 * Requete separee et non pas champ du profil : la declaration vit sur le TYPE
 * d'hyperviseur, elle change sans que les profils de host ne bougent. Le
 * formulaire se reconstruit a chaque changement de profil de machine.
 */
export function useHostProfileVariables(machineProfile: string) {
  return useQuery({
    queryKey: ['admin', 'host-profiles', 'variables', machineProfile],
    queryFn: () =>
      apiFetchJson<HypervisorVariable[]>(
        `/admin/host-profiles/variables/${encodeURIComponent(machineProfile)}`,
      ),
    enabled: Boolean(machineProfile),
    staleTime: 2 * 60 * 1000,
  })
}

export function useSaveHostProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (profile: HostProfile) =>
      apiFetchJson<HostProfile>(`/admin/host-profiles/${encodeURIComponent(profile.slug)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'host-profiles'] }),
  })
}

export function useDeleteHostProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetchVoid(`/admin/host-profiles/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'host-profiles'] }),
  })
}
