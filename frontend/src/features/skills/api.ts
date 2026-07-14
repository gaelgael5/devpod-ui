import { useMutation, useQuery, useQueries, useQueryClient } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'

export interface SkillResult {
  id: string
  skillId: string
  name: string
  installs: number
  source: string
}

export interface SkillsSearchResult {
  query: string
  searchType: string
  skills: SkillResult[]
}

export interface SkillGrant {
  id: number
  user_subject: string
  skill_id: string
  approved_hash: string | null
  statut: 'requested' | 'pending' | 'granted' | 'paused' | 'revoked'
  created: boolean
}

/** Risques remontés par l'audit skills.sh : { <analyseur>: { risk, score? } } */
export type SkillAudit = Record<string, { risk?: string; score?: number }>

export function useSkillsSearch(query: string, searchType: string, secretSlug: string) {
  return useQuery<SkillsSearchResult>({
    queryKey: ['skills-search', query, searchType, secretSlug],
    queryFn: () =>
      apiFetchJson<SkillsSearchResult>(
        `/me/skills/search?q=${encodeURIComponent(query)}&search_type=${searchType}` +
          (secretSlug ? `&secret_slug=${encodeURIComponent(secretSlug)}` : ''),
      ),
    enabled: query.trim() !== '',
    staleTime: 30 * 1000,
  })
}

/** Audits groupés par source pour les résultats affichés — un appel par source. */
export function useSkillsAudits(
  groups: { source: string; skillIds: string[] }[],
  secretSlug: string,
) {
  return useQueries({
    queries: groups.map((g) => ({
      queryKey: ['skills-audit', g.source, g.skillIds.join(','), secretSlug],
      queryFn: () =>
        apiFetchJson<Record<string, SkillAudit>>(
          `/me/skills/audit?source=${encodeURIComponent(g.source)}` +
            `&skills=${encodeURIComponent(g.skillIds.join(','))}` +
            (secretSlug ? `&secret_slug=${encodeURIComponent(secretSlug)}` : ''),
        ),
      staleTime: 5 * 60 * 1000,
    })),
  })
}

export function useMyGrants() {
  return useQuery<SkillGrant[]>({
    queryKey: ['skills-grants'],
    queryFn: () => apiFetchJson<SkillGrant[]>('/me/skills/grants'),
    staleTime: 30 * 1000,
  })
}

export function useRequestGrant() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (skillId: string) =>
      apiFetchJson<SkillGrant>('/me/skills/grants', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills-grants'] })
    },
  })
}

export type GrantAction = 'approve' | 'revoke' | 'pause' | 'resume'

export function useGrantAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ grantId, action }: { grantId: number; action: GrantAction }) =>
      apiFetchJson<SkillGrant>(`/me/skills/grants/${grantId}/${action}`, {
        method: 'POST',
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills-grants'] })
    },
  })
}

export interface SkillMdDoc {
  content: string
  hash: string
  approved_hash: string | null
}

export function useGrantSkillMd(grantId: number | null) {
  return useQuery<SkillMdDoc>({
    queryKey: ['skills-grant-md', grantId],
    queryFn: () => apiFetchJson<SkillMdDoc>(`/me/skills/grants/${grantId}/skillmd`),
    enabled: grantId !== null,
    staleTime: 5 * 60 * 1000,
  })
}
