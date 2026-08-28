import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useProviders } from './useBillingCatalog'
import { offreVide, useDeleteOffer, useOffers, type Offer } from './useBillingOffers'
import OfferEditor from './OfferEditor'

/** Montant en unites mineures rendu lisible, sans arrondi cache. */
function montant(minor: number, devise: string): string {
  return `${(minor / 100).toFixed(2)} ${devise}`
}

/**
 * Catalogue des offres d'abonnement.
 *
 * La liste montre d'abord ce qui decide de la vente : publiee ou non, et dans
 * quelles devises un prix existe. Une offre publiee sans prix ne serait
 * proposable a personne — le serveur le refuse, l'ecran le montre avant.
 */
export default function AdminBillingOffers() {
  const { t } = useTranslation()
  const { data: offres = [], isLoading } = useOffers()
  const { data: canaux = [] } = useProviders()
  const supprimer = useDeleteOffer()
  const [edite, setEdite] = useState<Offer | null>(null)

  function retirer(o: Offer) {
    // Une offre souscrite repond 409 avec « la depublier plutot » : c'est ce
    // message-la que l'utilisateur doit lire, pas une paraphrase.
    toast.promise(supprimer.mutateAsync(o.slug), {
      loading: '…',
      success: t('admin.offers.deleted', { slug: o.slug }),
      error: (err: Error) => err.message,
    })
  }

  return (
    <div className="mx-auto max-w-4xl p-4">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{t('admin.offers.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('admin.offers.description')}</p>
        </div>
        <Button size="sm" onClick={() => setEdite(offreVide())} className="shrink-0 gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          {t('admin.offers.new')}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}

      {!isLoading && offres.length === 0 && (
        <p className="rounded border border-dashed p-6 text-center text-sm text-muted-foreground">
          {t('admin.offers.empty')}
        </p>
      )}

      <div className="flex flex-col gap-2">
        {offres.map((o) => (
          <div
            key={o.slug}
            className="flex items-start justify-between gap-3 rounded-lg border p-3"
            data-testid={`offre-${o.slug}`}
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{o.label || o.slug}</span>
                <span className="font-mono text-xs text-muted-foreground">{o.slug}</span>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">
                  {t(`admin.offers.hosting.${o.hosting_type}`)}
                </span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${
                    o.published ? 'bg-emerald-500/15 text-emerald-700' : 'bg-muted'
                  }`}
                >
                  {t(o.published ? 'admin.offers.published' : 'admin.offers.draft')}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {o.prices.length === 0
                  ? t('admin.offers.noPrice')
                  : o.prices.map((p) => montant(p.amount_minor, p.currency)).join(' · ')}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t('admin.offers.quotas', {
                  workspaces: o.max_workspaces ?? t('admin.offers.unlimited'),
                  hosts: o.max_hosts_dedies ?? t('admin.offers.unlimited'),
                })}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                aria-label={t('admin.offers.edit')}
                onClick={() => setEdite(o)}
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-destructive"
                aria-label={t('admin.offers.delete')}
                onClick={() => retirer(o)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      {edite && <OfferEditor offre={edite} canaux={canaux} onClose={() => setEdite(null)} />}
    </div>
  )
}
