import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  useGrantAction,
  useGrantSkillMd,
  useMyGrants,
  type GrantAction,
  type SkillGrant,
} from './api'

const STATUS_ORDER: Record<string, number> = {
  pending: 0,
  requested: 1,
  granted: 2,
  paused: 3,
  revoked: 4,
}

/** Écran d'examen d'une demande : SKILL.md + comparaison de hash (dérive). */
function ReviewBox({ grantId }: { grantId: number }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, error } = useGrantSkillMd(grantId)
  if (isLoading) return <p className="text-xs text-muted-foreground">…</p>
  if (isError) return <p className="text-xs text-destructive">{(error as Error).message}</p>
  if (!data) return null
  const drifted = data.approved_hash !== null && data.approved_hash !== data.hash
  return (
    <div className="flex flex-col gap-2 rounded-md border bg-muted/30 p-3">
      <div className="flex flex-col gap-0.5 font-mono text-[11px] text-muted-foreground">
        <span>{t('skills.currentHash')} : {data.hash}</span>
        {data.approved_hash !== null && (
          <span className={drifted ? 'text-destructive' : ''}>
            {t('skills.approvedHash')} : {data.approved_hash}
            {drifted && ` — ${t('skills.hashDrifted')}`}
          </span>
        )}
      </div>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{data.content}</pre>
    </div>
  )
}

function GrantRow({ grant }: { grant: SkillGrant }) {
  const { t } = useTranslation()
  const act = useGrantAction()
  const [reviewOpen, setReviewOpen] = useState(false)

  function run(action: GrantAction) {
    act.mutate(
      { grantId: grant.id, action },
      {
        onSuccess: () => toast.success(t(`skills.actionDone.${action}`)),
        onError: (e: Error) => toast.error(e.message),
      },
    )
  }

  const isRevalidation = grant.statut === 'pending' && grant.approved_hash !== null

  return (
    <li className="flex flex-col gap-2 rounded-md border bg-background px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-mono text-sm">{grant.skill_id}</span>
        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
          {t(`skills.status.${grant.statut}`)}
        </span>
        {isRevalidation && (
          <span className="rounded bg-orange-500/10 px-1.5 py-0.5 text-[10px] uppercase text-orange-700 dark:text-orange-400">
            {t('skills.revalidation')}
          </span>
        )}
        {grant.statut === 'pending' && (
          <>
            <Button size="sm" variant="outline" onClick={() => setReviewOpen((o) => !o)}>
              {t('skills.review')}
            </Button>
            <Button size="sm" disabled={act.isPending} onClick={() => run('approve')}>
              {t('skills.approve')}
            </Button>
          </>
        )}
        {grant.statut === 'granted' && (
          <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => run('pause')}>
            {t('skills.pause')}
          </Button>
        )}
        {grant.statut === 'paused' && (
          <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => run('resume')}>
            {t('skills.resume')}
          </Button>
        )}
        {grant.statut !== 'revoked' && (
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            disabled={act.isPending}
            onClick={() => run('revoke')}
          >
            {t('skills.revoke')}
          </Button>
        )}
      </div>
      {reviewOpen && grant.statut === 'pending' && <ReviewBox grantId={grant.id} />}
    </li>
  )
}

/**
 * Onglet Validations — file des demandes pending (dont re-validations après
 * dérive de hash) et cycle de vie des grants. Toutes les actions sont
 * humaines ; la remise en service n'existe QUE ici (jamais côté MCP).
 */
export default function GrantsPanel() {
  const { t } = useTranslation()
  const { data: grants = [], isLoading } = useMyGrants()
  const sorted = useMemo(
    () =>
      [...grants].sort(
        (a, b) => (STATUS_ORDER[a.statut] ?? 9) - (STATUS_ORDER[b.statut] ?? 9) || a.id - b.id,
      ),
    [grants],
  )

  return (
    <div className="flex flex-col gap-3 border-t pt-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">{t('skills.validationsTitle')}</h3>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">…</p>
      ) : sorted.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('skills.noGrants')}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {sorted.map((g) => (
            <GrantRow key={g.id} grant={g} />
          ))}
        </ul>
      )}
    </div>
  )
}
