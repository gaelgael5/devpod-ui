import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { devisesIso } from '@/shared/iso'
import { useCurrencies, type PaymentProvider } from './useBillingCatalog'
import { enMajeur, enMineur, type OngletProps } from './offerDraft'
import type { OfferPrice } from './useBillingOffers'

interface Props extends OngletProps {
  canaux: PaymentProvider[]
}

/**
 * Comment l'offre se VEND : par quel canal, a quel prix, dans quelles devises.
 *
 * Le point a ne pas rater : le montant saisi est HT ou TTC selon le mode de
 * taxe du canal choisi. L'ecran le dit a cote du champ — sans quoi
 * l'administrateur ne sait pas ce qu'il tape, et la moitie des factures
 * partiraient fausses.
 */
export default function OfferPricingTab({ brouillon, setBrouillon, canaux }: Props) {
  const { t, i18n } = useTranslation()
  const canal = canaux.find((c) => c.slug === brouillon.provider_slug)
  const { data: acceptees = [] } = useCurrencies()
  const noms = useMemo(() => devisesIso(i18n.language), [i18n.language])

  // On ne propose QUE ce que l'application sait encaisser : offrir une devise
  // non acceptee produirait une offre invendable, decouverte au paiement.
  const catalogueDevises = useMemo(
    () =>
      acceptees
        .filter((d) => d.enabled)
        .map((d) => ({ code: d.code, label: noms.find((n) => n.code === d.code)?.label ?? d.code })),
    [acceptees, noms],
  )

  function majPrix(index: number, patch: Partial<OfferPrice>) {
    setBrouillon((b) => ({
      ...b,
      prices: b.prices.map((p, i) => (i === index ? { ...p, ...patch } : p)),
    }))
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5 rounded-lg border p-3">
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={brouillon.is_free}
            onChange={(e) =>
              // Cocher « gratuit » VIDE les prix : le serveur refuse une offre
              // gratuite qui en porte, et les garder caches ferait echouer
              // l'enregistrement sans que rien ne le montre.
              setBrouillon((b) => ({
                ...b,
                is_free: e.target.checked,
                prices: e.target.checked ? [] : b.prices,
              }))
            }
          />
          {t('admin.offers.isFree')}
        </label>
        <p className="text-xs text-muted-foreground">
          {t(brouillon.is_free ? 'admin.offers.isFreeOn' : 'admin.offers.isFreeOff')}
        </p>
      </div>

      {brouillon.is_free ? (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          {t('admin.offers.freeNoPricing')}
        </p>
      ) : (
      <>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="offre-canal">{t('admin.offers.provider')}</Label>
        <select
          id="offre-canal"
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
          value={brouillon.provider_slug ?? ''}
          onChange={(e) => setBrouillon((b) => ({ ...b, provider_slug: e.target.value || null }))}
        >
          <option value="">{t('admin.offers.noProvider')}</option>
          {canaux.map((c) => (
            <option key={c.slug} value={c.slug}>{c.label}</option>
          ))}
        </select>
      </div>

      <fieldset className="rounded-lg border p-3">
        <legend className="px-1 text-sm font-medium">{t('admin.offers.prices')}</legend>
        <div className="mb-3 flex flex-col gap-1.5">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={brouillon.prices_include_tax}
              onChange={(e) =>
                setBrouillon((b) => ({ ...b, prices_include_tax: e.target.checked }))
              }
            />
            {t('admin.offers.pricesIncludeTax')}
          </label>
          <p className="text-xs text-muted-foreground">
            {t(
              brouillon.prices_include_tax
                ? 'admin.offers.pricesIncludeTaxOn'
                : 'admin.offers.pricesIncludeTaxOff',
            )}
          </p>
          {canal && (
            <p className="text-xs text-muted-foreground">
              {t(`admin.offers.priceMeaning.${canal.tax_mode}`)}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-2">
          {brouillon.prices.map((p, i) => (
            // Empile sur mobile : trois champs cote a cote n'y laissaient voir
            // que des amorces tronquees, sans libelle pour dire lequel attend
            // un code et lequel un montant.
            <div
              key={i}
              className="flex flex-col gap-2 rounded-md border p-2 sm:flex-row sm:items-end sm:border-0 sm:p-0"
            >
              <div className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">{t('admin.offers.currency')}</span>
                <select
                  className="h-9 w-56 rounded-md border border-input bg-transparent px-2 text-sm"
                  value={p.currency}
                  onChange={(e) => majPrix(i, { currency: e.target.value })}
                  aria-label={t('admin.offers.currency')}
                  required
                >
                  <option value="">—</option>
                  {catalogueDevises
                    // Une devise deja tarifee sur cette offre ne se repropose
                    // pas : deux prix pour une meme devise ne voudraient rien
                    // dire.
                    .filter(
                      (c) =>
                        c.code === p.currency ||
                        !brouillon.prices.some((x) => x.currency === c.code),
                    )
                    .map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.code} · {c.label}
                      </option>
                    ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">{t('admin.offers.amount')}</span>
                <Input
                  className="w-32"
                  type="number"
                  step="0.01"
                  min={0}
                  value={enMajeur(p.amount_minor)}
                  onChange={(e) => majPrix(i, { amount_minor: enMineur(e.target.value) })}
                  aria-label={t('admin.offers.amount')}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1">
                <span className="text-xs text-muted-foreground">
                  {t('admin.offers.providerPriceId')}
                </span>
                <Input
                  className="font-mono"
                  placeholder={t('admin.offers.providerPriceIdPlaceholder')}
                  aria-label={t('admin.offers.providerPriceId')}
                  value={p.provider_price_id}
                  onChange={(e) => majPrix(i, { provider_price_id: e.target.value })}
                />
              </div>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-9 w-9 shrink-0 self-end text-destructive"
                aria-label={t('admin.offers.removePrice')}
                onClick={() =>
                  setBrouillon((b) => ({ ...b, prices: b.prices.filter((_, j) => j !== i) }))
                }
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
          {brouillon.prices.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {t('admin.offers.providerPriceIdHint')}
            </p>
          )}
        </div>

        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-2 gap-1.5"
          onClick={() =>
            setBrouillon((b) => ({
              ...b,
              prices: [...b.prices, { currency: '', amount_minor: 0, provider_price_id: '' }],
            }))
          }
        >
          <Plus className="h-3.5 w-3.5" />
          {t('admin.offers.addPrice')}
        </Button>

        {catalogueDevises.length === 0 && (
          <p className="mt-2 rounded border border-dashed p-2 text-xs text-muted-foreground">
            {t('admin.offers.noAcceptedCurrency')}
          </p>
        )}

        <div className="mt-4 flex flex-col gap-1.5 border-t pt-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={brouillon.auto_currencies}
              onChange={(e) => setBrouillon((b) => ({ ...b, auto_currencies: e.target.checked }))}
            />
            {t('admin.offers.autoCurrencies')}
          </label>
          <p className="text-xs text-muted-foreground">{t('admin.offers.autoCurrenciesHelp')}</p>
          {brouillon.auto_currencies && (
            <div className="flex items-center gap-2">
              <Label htmlFor="offre-majoration" className="text-xs font-normal">
                {t('admin.offers.markup')}
              </Label>
              <Input
                id="offre-majoration"
                className="w-28"
                type="number"
                step="0.01"
                min={0.01}
                value={String(brouillon.currency_markup)}
                onChange={(e) => setBrouillon((b) => ({ ...b, currency_markup: e.target.value }))}
              />
            </div>
          )}
        </div>
      </fieldset>
      </>
      )}

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={brouillon.published}
          onChange={(e) => setBrouillon((b) => ({ ...b, published: e.target.checked }))}
        />
        {t('admin.offers.publish')}
      </label>
    </div>
  )
}
