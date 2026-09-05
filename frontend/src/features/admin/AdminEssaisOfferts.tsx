import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { apiFetchJson } from '@/shared/api/client'
import { useAdminUsers } from './useAdminUsers'
import { useOffers } from './useBillingOffers'

/**
 * Offrir une période d'essai gratuite — l'onglet « Essais » de la page
 * Abonnements. Les trois décisions de la fiche : un forfait obligatoire, une
 * date de fin avec raccourcis, un ou plusieurs bénéficiaires d'un geste.
 *
 * L'appel est en LOT et le backend répond compte par compte : le résultat
 * s'affiche ligne à ligne — un refus (essai déjà offert, abonnement en cours)
 * ne cache pas les essais accordés du même envoi.
 */

interface ResultatEssai {
  login: string
  accorde: boolean
  motif: string
  subscription_id: string | null
}

/** Raccourcis de la fiche, en jours. Ils REMPLISSENT le champ date : la valeur
 * envoyée est toujours celle que l'admin voit dans le champ. */
const RACCOURCIS: Array<{ cle: string; jours: number }> = [
  { cle: 'uneSemaine', jours: 7 },
  { cle: 'deuxSemaines', jours: 14 },
  { cle: 'unMois', jours: 30 },
  { cle: 'deuxMois', jours: 61 },
  { cle: 'troisMois', jours: 91 },
]

function dansNJours(jours: number): string {
  const d = new Date()
  d.setDate(d.getDate() + jours)
  return d.toISOString().slice(0, 10)
}

export default function AdminEssaisOfferts() {
  const { t } = useTranslation()
  const { data: offres } = useOffers()
  const { listQuery } = useAdminUsers()
  const [offerSlug, setOfferSlug] = useState('')
  const [fin, setFin] = useState(() => dansNJours(14))
  const [selection, setSelection] = useState<Set<string>>(new Set())
  const [filtre, setFiltre] = useState('')
  const [resultats, setResultats] = useState<ResultatEssai[] | null>(null)

  const offrir = useMutation({
    mutationFn: () =>
      apiFetchJson<{ resultats: ResultatEssai[] }>('/admin/billing/essais', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          offer_slug: offerSlug,
          logins: [...selection],
          // Fin de journée UTC du jour choisi : un essai « jusqu'au 15 » couvre
          // le 15, il ne s'arrête pas à son premier instant.
          fin: `${fin}T23:59:00Z`,
        }),
      }),
    onSuccess: (data) => {
      setResultats(data.resultats)
      const accordes = data.resultats.filter((r) => r.accorde).length
      if (accordes > 0) toast.success(t('admin.essais.accordes', { count: accordes }))
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const comptes = useMemo(() => {
    const tous = listQuery.data ?? []
    const q = filtre.trim().toLowerCase()
    if (!q) return tous
    return tous.filter(
      (u) =>
        u.login.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        u.display_name.toLowerCase().includes(q),
    )
  }, [listQuery.data, filtre])

  function basculer(login: string) {
    setSelection((cur) => {
      const suivant = new Set(cur)
      if (suivant.has(login)) suivant.delete(login)
      else suivant.add(login)
      return suivant
    })
  }

  const pret = offerSlug !== '' && selection.size > 0 && fin !== ''

  return (
    <div className="flex max-w-lg flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="essai-offre">{t('admin.essais.offre')}</Label>
        <select
          id="essai-offre"
          value={offerSlug}
          onChange={(e) => setOfferSlug(e.target.value)}
          className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
        >
          <option value="">{t('admin.essais.choisirOffre')}</option>
          {(offres ?? []).map((o) => (
            <option key={o.slug} value={o.slug}>
              {o.label || o.slug}
              {o.published ? '' : ` — ${t('admin.essais.nonPubliee')}`}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="essai-fin">{t('admin.essais.fin')}</Label>
        <Input
          id="essai-fin"
          type="date"
          value={fin}
          min={dansNJours(1)}
          onChange={(e) => setFin(e.target.value)}
        />
        <div className="flex flex-wrap gap-1.5">
          {RACCOURCIS.map((r) => (
            <button
              key={r.cle}
              type="button"
              className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setFin(dansNJours(r.jours))}
            >
              {t(`admin.essais.raccourci.${r.cle}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>{t('admin.essais.beneficiaires', { count: selection.size })}</Label>
        <Input
          value={filtre}
          onChange={(e) => setFiltre(e.target.value)}
          placeholder={t('admin.essais.filtrer')}
        />
        <div className="max-h-56 overflow-y-auto rounded-md border p-2">
          {listQuery.isLoading && (
            <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
          )}
          {comptes.map((u) => (
            <label
              key={u.login}
              className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-muted/50"
            >
              <input
                type="checkbox"
                checked={selection.has(u.login)}
                onChange={() => basculer(u.login)}
              />
              <span className="font-medium">{u.login}</span>
              <span className="truncate text-xs text-muted-foreground">
                {u.display_name || u.email}
              </span>
            </label>
          ))}
          {!listQuery.isLoading && comptes.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('admin.essais.aucunCompte')}</p>
          )}
        </div>
      </div>

      <div>
        <Button onClick={() => offrir.mutate()} disabled={!pret || offrir.isPending}>
          {offrir.isPending ? '…' : t('admin.essais.offrir', { count: selection.size })}
        </Button>
      </div>

      {resultats && (
        <ul className="flex flex-col gap-1 rounded-md border p-3" data-testid="essais-resultats">
          {resultats.map((r) => (
            <li key={r.login} className="flex items-baseline gap-2 text-sm">
              <span className="font-medium">{r.login}</span>
              {r.accorde ? (
                <span className="text-emerald-600 dark:text-emerald-400">
                  {t('admin.essais.accorde')}
                </span>
              ) : (
                <span className="text-destructive">{r.motif}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
