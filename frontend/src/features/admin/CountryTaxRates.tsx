import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  useAddTaxRate, useCloseTaxRate, useDeleteTaxRate, useTaxRates, type TaxRate,
} from './useBillingCatalog'

interface Props {
  code: string
}

/** 20 (pourcent saisi) → "0.2000" (fraction attendue par le serveur). */
function enFraction(pourcent: string): string {
  return (Number(pourcent) / 100).toFixed(4)
}

function enPourcent(taux: number | string): string {
  return (Number(taux) * 100).toFixed(2).replace(/\.00$/, '')
}

/**
 * Historique des taux de taxe d'un pays.
 *
 * Un taux ne s'EDITE pas : il se clot, et un nouveau prend la suite. Cet ecran
 * doit rendre ce geste impossible, sinon une facture emise l'an dernier cesse
 * d'etre reproductible avec le taux de l'epoque — et la facturation legale perd
 * sa valeur probante au premier changement de TVA.
 *
 * Les ecritures partent immediatement : un taux n'est pas un champ de
 * formulaire, c'est un evenement dans une histoire.
 */
export default function CountryTaxRates({ code }: Props) {
  const { t } = useTranslation()
  const { data: taux = [], isLoading } = useTaxRates(code)
  const ajouter = useAddTaxRate(code)
  const clore = useCloseTaxRate(code)
  const supprimer = useDeleteTaxRate(code)
  const [ouvert, setOuvert] = useState(false)
  const [neuf, setNeuf] = useState({ label: '', pourcent: '', valid_from: '', region: '' })

  function soumettre() {
    const charge: Omit<TaxRate, 'id'> = {
      country_code: code,
      region: neuf.region,
      rate: enFraction(neuf.pourcent),
      label: neuf.label,
      valid_from: neuf.valid_from,
      valid_to: null,
    }
    toast.promise(ajouter.mutateAsync(charge), {
      loading: '…',
      success: () => {
        setOuvert(false)
        setNeuf({ label: '', pourcent: '', valid_from: '', region: '' })
        return t('admin.billing.taxRateAdded')
      },
      error: (err: Error) => err.message,
    })
  }

  function fermer(rate: TaxRate) {
    const valeur = window.prompt(t('admin.billing.closePrompt'), rate.valid_from)
    if (!valeur) return
    toast.promise(clore.mutateAsync({ id: rate.id as number, valid_to: valeur }), {
      loading: '…',
      success: t('admin.billing.taxRateClosed'),
      error: (err: Error) => err.message,
    })
  }

  return (
    <fieldset className="rounded-lg border p-3">
      <legend className="px-1 text-sm font-medium">{t('admin.billing.taxRates')}</legend>
      <p className="mb-2 text-xs text-muted-foreground">{t('admin.billing.taxRatesHelp')}</p>

      {isLoading && <p className="text-xs text-muted-foreground">{t('common.loading')}</p>}

      {!isLoading && taux.length === 0 && (
        <p className="text-xs text-muted-foreground">{t('admin.billing.taxRatesEmpty')}</p>
      )}

      <div className="flex flex-col gap-1.5">
        {taux.map((r) => (
          <div
            key={r.id ?? `${r.valid_from}-${r.rate}`}
            className="flex items-center gap-2 rounded border px-2 py-1.5 text-sm"
            data-testid={`taux-${r.id}`}
          >
            <span className="font-medium">{enPourcent(r.rate)} %</span>
            <span className="text-muted-foreground">{r.label}</span>
            {r.region && <span className="font-mono text-xs">{r.region}</span>}
            <span className="ml-auto text-xs text-muted-foreground">
              {r.valid_to
                ? t('admin.billing.period', { from: r.valid_from, to: r.valid_to })
                : t('admin.billing.periodOpen', { from: r.valid_from })}
            </span>
            {!r.valid_to && (
              <Button type="button" size="sm" variant="outline" onClick={() => fermer(r)}>
                {t('admin.billing.close')}
              </Button>
            )}
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-destructive"
              aria-label={t('admin.billing.deleteTaxRate')}
              onClick={() =>
                toast.promise(supprimer.mutateAsync(r.id as number), {
                  loading: '…',
                  success: t('admin.billing.taxRateDeleted'),
                  error: (err: Error) => err.message,
                })
              }
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>

      {ouvert ? (
        <div className="mt-2 flex flex-wrap items-end gap-2 rounded border border-dashed p-2">
          <Input
            className="w-40"
            placeholder={t('admin.billing.taxRateLabel')}
            aria-label={t('admin.billing.taxRateLabel')}
            value={neuf.label}
            onChange={(e) => setNeuf((n) => ({ ...n, label: e.target.value }))}
          />
          <Input
            className="w-24"
            type="number"
            step="0.01"
            placeholder="20"
            aria-label={t('admin.billing.taxRatePercent')}
            value={neuf.pourcent}
            onChange={(e) => setNeuf((n) => ({ ...n, pourcent: e.target.value }))}
          />
          <Input
            className="w-40"
            type="date"
            aria-label={t('admin.billing.validFrom')}
            value={neuf.valid_from}
            onChange={(e) => setNeuf((n) => ({ ...n, valid_from: e.target.value }))}
          />
          <Input
            className="w-28"
            placeholder={t('admin.billing.region')}
            aria-label={t('admin.billing.region')}
            value={neuf.region}
            onChange={(e) => setNeuf((n) => ({ ...n, region: e.target.value }))}
          />
          <Button type="button" size="sm" onClick={soumettre}>
            {t('common.save')}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setOuvert(false)}>
            {t('common.cancel')}
          </Button>
        </div>
      ) : (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-2 gap-1.5"
          onClick={() => setOuvert(true)}
        >
          <Plus className="h-3.5 w-3.5" />
          {t('admin.billing.addTaxRate')}
        </Button>
      )}
    </fieldset>
  )
}
