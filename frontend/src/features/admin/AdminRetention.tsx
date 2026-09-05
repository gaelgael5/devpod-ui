import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { apiFetchJson } from '@/shared/api/client'

/**
 * Les délais de rétention — l'onglet Rétention de la page Abonnements.
 *
 * Deux nombres, mais pas anodins : c'est la fenêtre entre l'arrêt d'un
 * workspace non payé et sa DESTRUCTION. Le backend refuse zéro (détruire à la
 * première passe du balayeur ne laisserait aucune fenêtre pour archiver) ;
 * l'écran le dit plutôt que de laisser le refus arriver en toast.
 */

interface PolitiqueRetention {
  echec_paiement_jours: number
  resiliation_jours: number
}

function ChampDelai({
  id,
  label,
  hint,
  value,
  onChange,
}: {
  id: string
  label: string
  hint: string
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        min={1}
        value={Number.isNaN(value) ? '' : value}
        onChange={(e) => onChange(e.target.valueAsNumber)}
        className="max-w-32"
      />
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

function Formulaire({ initial }: { initial: PolitiqueRetention }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [echec, setEchec] = useState(initial.echec_paiement_jours)
  const [resiliation, setResiliation] = useState(initial.resiliation_jours)

  const save = useMutation({
    mutationFn: () =>
      apiFetchJson<PolitiqueRetention>('/admin/billing/retention/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ echec_paiement_jours: echec, resiliation_jours: resiliation }),
      }),
    onSuccess: () => {
      toast.success(t('admin.retention.saved'))
      void qc.invalidateQueries({ queryKey: ['admin', 'billing', 'retention'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const invalide = !(echec >= 1) || !(resiliation >= 1)

  return (
    <div className="flex max-w-lg flex-col gap-4">
      <p className="text-sm text-muted-foreground">{t('admin.retention.intro')}</p>
      <ChampDelai
        id="ret-echec"
        label={t('admin.retention.echec')}
        hint={t('admin.retention.echecHint')}
        value={echec}
        onChange={setEchec}
      />
      <ChampDelai
        id="ret-resiliation"
        label={t('admin.retention.resiliation')}
        hint={t('admin.retention.resiliationHint')}
        value={resiliation}
        onChange={setResiliation}
      />
      {invalide && <p className="text-sm text-destructive">{t('admin.retention.minimum')}</p>}
      <div>
        <Button onClick={() => save.mutate()} disabled={save.isPending || invalide}>
          {save.isPending ? '…' : t('common.save')}
        </Button>
      </div>
    </div>
  )
}

export default function AdminRetention() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useQuery<PolitiqueRetention>({
    queryKey: ['admin', 'billing', 'retention'],
    queryFn: () => apiFetchJson<PolitiqueRetention>('/admin/billing/retention/config'),
  })

  if (isLoading) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  if (isError || !data)
    return <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>
  return <Formulaire initial={data} />
}
