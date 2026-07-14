import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Search, ShieldQuestion, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useSecrets } from '@/features/secrets/api'
import GrantsPanel from './GrantsPanel'
import {
  useMyGrants,
  useRequestGrant,
  useSkillsAudits,
  useSkillsSearch,
  type SkillAudit,
  type SkillResult,
} from './api'

const DISPLAYED = 20

/** Pire risque agrégé des analyseurs (safe < low < medium/moderate < high/critical). */
function worstRisk(audit: SkillAudit | undefined): string | null {
  if (!audit) return null
  const order = ['safe', 'low', 'medium', 'moderate', 'high', 'critical']
  let worst: string | null = null
  for (const entry of Object.values(audit)) {
    const risk = entry?.risk?.toLowerCase()
    if (!risk) continue
    if (worst === null || order.indexOf(risk) > order.indexOf(worst)) worst = risk
  }
  return worst
}

const RISK_CLASS: Record<string, string> = {
  safe: 'bg-green-500/10 text-green-700 dark:text-green-400',
  low: 'bg-yellow-500/10 text-yellow-700 dark:text-yellow-400',
  medium: 'bg-orange-500/10 text-orange-700 dark:text-orange-400',
  moderate: 'bg-orange-500/10 text-orange-700 dark:text-orange-400',
  high: 'bg-red-500/10 text-red-700 dark:text-red-400',
  critical: 'bg-red-500/10 text-red-700 dark:text-red-400',
}

/**
 * Onglet Skills — recherche skills.sh (via l'adaptateur serveur), audit de
 * sécurité par source, et demande de validation : « Ajouter » crée un grant
 * PENDING (jamais une installation — la validation est humaine, onglet
 * Validations).
 */
export default function SkillsTab() {
  const { t } = useTranslation()
  const { data: secrets = [] } = useSecrets('SKILLS_SH')
  const [secretSlug, setSecretSlug] = useState('')
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')

  // fuzzy pour un mot, sémantique au-delà — le searchType effectif renvoyé
  // par skills.sh est affiché en badge (l'amont peut retomber en fuzzy).
  const searchType = query.trim().includes(' ') ? 'semantic' : 'fuzzy'
  const search = useSkillsSearch(query, searchType, secretSlug)
  const { data: grants = [] } = useMyGrants()
  const requestGrant = useRequestGrant()

  const results = useMemo(
    () => (search.data?.skills ?? []).slice(0, DISPLAYED),
    [search.data],
  )
  const auditGroups = useMemo(() => {
    const bySource = new Map<string, string[]>()
    for (const r of results) {
      const ids = bySource.get(r.source) ?? []
      ids.push(r.skillId)
      bySource.set(r.source, ids)
    }
    return [...bySource.entries()].map(([source, skillIds]) => ({ source, skillIds }))
  }, [results])
  const auditQueries = useSkillsAudits(auditGroups, secretSlug)
  const auditBySource = useMemo(() => {
    const map = new Map<string, Record<string, SkillAudit>>()
    auditGroups.forEach((g, i) => {
      const data = auditQueries[i]?.data
      if (data) map.set(g.source, data)
    })
    return map
  }, [auditGroups, auditQueries])

  const grantBySkill = useMemo(
    () => new Map(grants.map((g) => [g.skill_id, g.statut])),
    [grants],
  )

  function add(result: SkillResult) {
    requestGrant.mutate(result.id, {
      onSuccess: () => toast.success(t('skills.requested', { name: result.name })),
      onError: (e: Error) => toast.error(e.message),
    })
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border bg-muted/40 p-5">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">{t('skills.title')}</h2>
      </div>
      <p className="text-sm text-muted-foreground">{t('skills.subtitle')}</p>

      <div className="flex flex-wrap items-end gap-2">
        {secrets.length > 0 && (
          <label className="flex flex-col gap-1 text-xs">
            {t('skills.secretLabel')}
            <select
              value={secretSlug}
              onChange={(e) => setSecretSlug(e.target.value)}
              className="h-9 rounded-md border bg-background px-2 text-sm"
            >
              <option value="">{t('skills.noSecret')}</option>
              {secrets.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') setQuery(draft.trim())
          }}
          placeholder={t('skills.searchPlaceholder')}
          className="h-9 min-w-[14rem] flex-1"
        />
        <Button
          size="sm"
          disabled={draft.trim() === '' || search.isFetching}
          onClick={() => setQuery(draft.trim())}
        >
          <Search className="mr-1 h-3.5 w-3.5" />
          {search.isFetching ? t('skills.searching') : t('skills.searchBtn')}
        </Button>
      </div>

      {search.isError && (
        <p className="text-sm text-destructive">{(search.error as Error).message}</p>
      )}

      {search.data && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="rounded bg-muted px-1.5 py-0.5 uppercase">
            {search.data.searchType}
          </span>
          <span>{t('skills.resultsCount', { total: search.data.skills.length })}</span>
        </div>
      )}

      {search.data && search.data.skills.length === 0 && !search.isFetching && (
        <p className="text-sm text-muted-foreground">{t('skills.noResults', { q: query })}</p>
      )}

      {results.length > 0 && (
        <ul className="flex flex-col gap-2">
          {results.map((r) => {
            const risk = worstRisk(auditBySource.get(r.source)?.[r.skillId])
            const grantStatus = grantBySkill.get(r.id)
            return (
              <li
                key={r.id}
                className="flex flex-wrap items-center gap-2 rounded-md border bg-background px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-medium">{r.name}</span>
                    {risk ? (
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${RISK_CLASS[risk] ?? 'bg-muted text-muted-foreground'}`}
                      >
                        {risk}
                      </span>
                    ) : (
                      <ShieldQuestion className="h-3.5 w-3.5 text-muted-foreground/50" />
                    )}
                  </div>
                  <div className="flex gap-3 text-xs text-muted-foreground">
                    <span className="truncate">{r.source}</span>
                    <span className="inline-flex items-center gap-1">
                      <Download className="h-3 w-3" />
                      {r.installs}
                    </span>
                  </div>
                </div>
                {grantStatus ? (
                  <span className="rounded bg-muted px-2 py-1 text-xs text-muted-foreground">
                    {t(`skills.status.${grantStatus}`)}
                  </span>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={requestGrant.isPending}
                    onClick={() => add(r)}
                  >
                    {t('skills.add')}
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <GrantsPanel />
    </div>
  )
}
