import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CreditCard, Globe, Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  canalVide, paysVide, useCountries, useDeleteCountry, useDeleteProvider, useProviders,
  type Country, type PaymentProvider,
} from './useBillingCatalog'
import CountryEditor from './CountryEditor'
import PaymentProviderEditor from './PaymentProviderEditor'

/**
 * Catalogue de facturation : ou l'on vend, et par quel canal.
 *
 * Deux listes cote a cote parce que la relation va dans un sens : un pays
 * REFERENCE des canaux, un canal sert plusieurs pays. On cree donc le canal
 * d'abord, on le rattache ensuite depuis la fiche du pays.
 */
export default function AdminBillingCatalog() {
  const { t } = useTranslation()
  const { data: pays = [], isLoading: chargePays } = useCountries()
  const { data: canaux = [], isLoading: chargeCanaux } = useProviders()
  const supprimerPays = useDeleteCountry()
  const supprimerCanal = useDeleteProvider()
  const [paysEdite, setPaysEdite] = useState<Country | null>(null)
  const [canalEdite, setCanalEdite] = useState<PaymentProvider | null>(null)

  function retirerPays(p: Country) {
    toast.promise(supprimerPays.mutateAsync(p.code), {
      loading: '…',
      success: t('admin.billing.countryDeleted', { code: p.code }),
      error: (err: Error) => err.message,
    })
  }

  function retirerCanal(c: PaymentProvider) {
    // Un canal reference renvoie 409 : le message du serveur dit quoi faire
    // (desactiver), l'IHM se garde de le paraphraser.
    toast.promise(supprimerCanal.mutateAsync(c.slug), {
      loading: '…',
      success: t('admin.billing.providerDeleted', { slug: c.slug }),
      error: (err: Error) => err.message,
    })
  }

  return (
    <div className="mx-auto max-w-4xl p-4">
      <div className="mb-6">
        <h1 className="text-xl font-semibold">{t('admin.billing.title')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t('admin.billing.description')}</p>
      </div>

      <section className="mb-8">
        <div className="mb-3 flex items-start justify-between gap-4">
          <h2 className="flex items-center gap-2 font-medium">
            <Globe className="h-4 w-4" />
            {t('admin.billing.countries')}
          </h2>
          <Button size="sm" onClick={() => setPaysEdite(paysVide())} className="shrink-0 gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            {t('admin.billing.newCountry')}
          </Button>
        </div>

        {chargePays && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}

        {!chargePays && pays.length === 0 && (
          <p className="rounded border border-dashed p-6 text-center text-sm text-muted-foreground">
            {t('admin.billing.countriesEmpty')}
          </p>
        )}

        <div className="flex flex-col gap-2">
          {pays.map((p) => (
            <div
              key={p.code}
              className="flex items-center justify-between gap-3 rounded-lg border p-3"
              data-testid={`pays-${p.code}`}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium">{p.code}</span>
                  <span>{p.label}</span>
                  {!p.enabled && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">
                      {t('admin.billing.disabled')}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  aria-label={t('admin.billing.editCountry')}
                  onClick={() => setPaysEdite(p)}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-destructive"
                  aria-label={t('admin.billing.deleteCountry')}
                  onClick={() => retirerPays(p)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-start justify-between gap-4">
          <h2 className="flex items-center gap-2 font-medium">
            <CreditCard className="h-4 w-4" />
            {t('admin.billing.providers')}
          </h2>
          <Button size="sm" onClick={() => setCanalEdite(canalVide())} className="shrink-0 gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            {t('admin.billing.newProvider')}
          </Button>
        </div>

        {chargeCanaux && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}

        {!chargeCanaux && canaux.length === 0 && (
          <p className="rounded border border-dashed p-6 text-center text-sm text-muted-foreground">
            {t('admin.billing.providersEmpty')}
          </p>
        )}

        <div className="flex flex-col gap-2">
          {canaux.map((c) => (
            <div
              key={c.slug}
              className="flex items-center justify-between gap-3 rounded-lg border p-3"
              data-testid={`canal-${c.slug}`}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{c.label}</span>
                  <span className="font-mono text-xs text-muted-foreground">{c.slug}</span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">
                    {c.kind}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">
                    {t(`admin.billing.taxMode.${c.tax_mode}`)}
                  </span>
                  {!c.enabled && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">
                      {t('admin.billing.disabled')}
                    </span>
                  )}
                </div>
                {c.secret_slug && (
                  <p className="mt-1 font-mono text-xs text-muted-foreground">{c.secret_slug}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  aria-label={t('admin.billing.editProvider')}
                  onClick={() => setCanalEdite(c)}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-destructive"
                  aria-label={t('admin.billing.deleteProvider')}
                  onClick={() => retirerCanal(c)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {paysEdite && (
        <CountryEditor
          pays={paysEdite}
          canaux={canaux}
          onClose={() => setPaysEdite(null)}
        />
      )}
      {canalEdite && (
        <PaymentProviderEditor canal={canalEdite} onClose={() => setCanalEdite(null)} />
      )}
    </div>
  )
}
