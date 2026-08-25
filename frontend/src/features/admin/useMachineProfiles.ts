import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson, apiFetchVoid } from '@/shared/api/client'

export { slugifier } from '@/shared/slug'

/** Une recette à poser sur la machine, avec les valeurs de ses options. */
export interface ProfileRecipe {
  key: string
  options: Record<string, string>
}

/** Un service Docker lancé au démarrage : un template compose et ses paramètres. */
export interface ProfileService {
  template_id: string
  /** Nom du déploiement — distinct du template, deux instances peuvent coexister. */
  deployment_id: string
  params: Record<string, string>
}

export interface MachineProfile {
  slug: string
  label: string
  /**
   * Meme vocabulaire que l'usage d'un host, a un detail pres : la machine de
   * test s'ecrit `test` ici (valeur historique) et `tests` la-bas.
   */
  machine_type: 'test' | 'ressources' | 'workspaces' | 'autres'
  hypervisor_type: string
  params: Record<string, string>
  recipes: ProfileRecipe[]
  services: ProfileService[]
}

export function useMachineProfiles() {
  return useQuery({
    queryKey: ['admin', 'machine-profiles'],
    queryFn: () => apiFetchJson<MachineProfile[]>('/admin/machine-profiles'),
  })
}

export function useSaveMachineProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (profile: MachineProfile) =>
      apiFetchJson<MachineProfile>(
        `/admin/machine-profiles/${encodeURIComponent(profile.slug)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(profile),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'machine-profiles'] }),
  })
}

export function useDeleteMachineProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      apiFetchVoid(`/admin/machine-profiles/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'machine-profiles'] }),
  })
}

/** Profil vierge, prêt à être édité. */
export function profilVide(hypervisorType: string): MachineProfile {
  return {
    slug: '',
    label: '',
    machine_type: 'test',
    hypervisor_type: hypervisorType,
    params: {},
    recipes: [],
    services: [],
  }
}

/**
 * Nom de déploiement libre pour un template donné.
 *
 * Deux déploiements de même nom sont refusés par le modèle — même répertoire
 * distant, même projet compose, le second écraserait le premier. Autant ne pas
 * les proposer : la seconde instance d'un template devient `<id>-2`.
 */
export function nomDeploiementLibre(templateId: string, pris: Iterable<string>): string {
  const occupes = new Set(pris)
  if (!occupes.has(templateId)) return templateId
  let n = 2
  while (occupes.has(`${templateId}-${n}`)) n++
  return `${templateId}-${n}`
}
