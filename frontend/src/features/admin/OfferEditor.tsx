import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { slugifier } from '@/shared/slug'
import type { PaymentProvider } from './useBillingCatalog'
import {
  useSaveOffer, type HostingType, type Offer, type OfferPrice,
} from './useBillingOffers'

interface Props {
  offre: Offer
  canaux: PaymentProvider[]
  onClose: () => void
}

const LANGUES = ['fr', 'en'] as const
const HEBERGEMENTS: HostingType[] = ['mutualise', 'dedie']

/** "12,34" saisi → 1234 centimes. L'arrondi se fait ici, une seule fois. */
function enMineur(saisi: string): number {
  return Math.round(Number(saisi.replace(',', '.')) * 100)
}

function enMajeur(minor: number): string {
  return (minor / 100).toFixed(2)
}

/**
 * Edition d'une offre.
 *
 * Le point a ne pas rater : le montant saisi est HT ou TTC selon le mode de
 * taxe du canal choisi. L'ecran le dit a cote du champ — sans quoi
 * l'administrateur ne sait pas ce qu'il tape, et la moitie des factures
 * partiraient fausses.
 */
export default function OfferEditor({ offre, canaux, onClose }: Props) {
  const { t } = useTranslation()
  const existant = Boolean(offre.slug)
  const [brouillon, setBrouillon] = useState<Offer>(offre)
  const [slugManuel, setSlugManuel] = useState(existant)
  const [manquantes, setManquantes] = useState<string[]>([])
  const enregistrer = useSaveOffer()

  const canal = canaux.find((c) => c.slug === brouillon.provider_slug)

  function setLabel(langue: string, texte: string) {
    setBrouillon((b) => {
      const labels = { ...b.labels, [langue]: texte }
      const slug = slugManuel ? b.slug : slugifier(labels.fr || labels.en || '')
      return { ...b, labels, slug }
    })
  }

  function setQuota(champ: 'max_workspaces' | 'max_hosts_dedies', valeur: string) {
    // Vide = illimite, et non zero : zero interdirait tout.
    setBrouillon((b) => ({ ...b, [champ]: valeur === '' ? null : Number(valeur) }))
  }

  function majPrix(index: number, patch: Partial<OfferPrice>) {
    setBrouillon((b) => ({
      ...b,
      prices: b.prices.map((p, i) => (i === index ? { ...p, ...patch } : p)),
    }))
  }

  function soumettre(e: React.FormEvent) {
    e.preventDefault()
    const prices = brouillon.prices.filter((p) => p.currency !== '')
    toast.promise(enregistrer.mutateAsync({ ...brouillon, prices }), {
      loading: '…',
      success: (res) => {
        setManquantes(res.devises_manquantes)
        // Devises manquantes : pas un refus — l'offre reste vendable ailleurs —
        // mais l'absence doit se voir a la saisie, pas dans une page vide.
        if (res.devises_manquantes.length === 0) onClose()
        return t('admin.offers.saved', { slug: brouillon.slug })
      },
      error: (err: Error) => err.message,
    })
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{existant ? t('admin.offers.edit') : t('admin.offers.new')}</DialogTitle>
          <DialogDescription>{t('admin.offers.help')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={soumettre} className="flex flex-col gap-4">
          {LANGUES.map((lng) => (
            <div key={lng} className="flex flex-col gap-1.5">
              <Label htmlFor={`offre-label-${lng}`}>
                {t('admin.offers.label', { lng: lng.toUpperCase() })}
              </Label>
              <Input
                id={`offre-label-${lng}`}
                value={brouillon.labels[lng] ?? ''}
                onChange={(e) => setLabel(lng, e.target.value)}
                required={lng === 'fr'}
              />
              <Input
                aria-label={t('admin.offers.descriptionField', { lng: lng.toUpperCase() })}
                placeholder={t('admin.offers.descriptionField', { lng: lng.toUpperCase() })}
                value={brouillon.descriptions[lng] ?? ''}
                onChange={(e) =>
                  setBrouillon((b) => ({
                    ...b,
                    descriptions: { ...b.descriptions, [lng]: e.target.value },
                  }))
                }
              />
            </div>
          ))}

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="offre-slug">{t('admin.offers.slug')}</Label>
              <Input
                id="offre-slug"
                className="font-mono"
                value={brouillon.slug}
                onChange={(e) => {
                  setSlugManuel(true)
                  setBrouillon((b) => ({ ...b, slug: e.target.value }))
                }}
                pattern="^[a-z0-9][a-z0-9-]{0,62}$"
                required
                disabled={existant}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="offre-hebergement">{t('admin.offers.hostingType')}</Label>
              <select
                id="offre-hebergement"
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                value={brouillon.hosting_type}
                onChange={(e) =>
                  setBrouillon((b) => ({ ...b, hosting_type: e.target.value as HostingType }))
                }
              >
                {HEBERGEMENTS.map((h) => (
                  <option key={h} value={h}>{t(`admin.offers.hosting.${h}`)}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="offre-ws">{t('admin.offers.maxWorkspaces')}</Label>
              <Input
                id="offre-ws"
                type="number"
                min={1}
                value={brouillon.max_workspaces ?? ''}
                onChange={(e) => setQuota('max_workspaces', e.target.value)}
                placeholder={t('admin.offers.unlimited')}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="offre-hosts">{t('admin.offers.maxHosts')}</Label>
              <Input
                id="offre-hosts"
                type="number"
                min={1}
                value={brouillon.max_hosts_dedies ?? ''}
                onChange={(e) => setQuota('max_hosts_dedies', e.target.value)}
                placeholder={t('admin.offers.unlimited')}
              />
            </div>
          </div>
          <p className="-mt-2 text-xs text-muted-foreground">{t('admin.offers.quotaHelp')}</p>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="offre-canal">{t('admin.offers.provider')}</Label>
            <select
              id="offre-canal"
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
              value={brouillon.provider_slug ?? ''}
              onChange={(e) =>
                setBrouillon((b) => ({ ...b, provider_slug: e.target.value || null }))
              }
            >
              <option value="">{t('admin.offers.noProvider')}</option>
              {canaux.map((c) => (
                <option key={c.slug} value={c.slug}>{c.label}</option>
              ))}
            </select>
          </div>

          <fieldset className="rounded-lg border p-3">
            <legend className="px-1 text-sm font-medium">{t('admin.offers.prices')}</legend>
            <p className="mb-2 text-xs text-muted-foreground">
              {canal
                ? t(`admin.offers.priceMeaning.${canal.tax_mode}`)
                : t('admin.offers.priceMeaningUnknown')}
            </p>
            <div className="flex flex-col gap-2">
              {brouillon.prices.map((p, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    className="w-24 font-mono uppercase"
                    value={p.currency}
                    onChange={(e) => majPrix(i, { currency: e.target.value.toUpperCase() })}
                    pattern="^[A-Z]{3}$"
                    maxLength={3}
                    aria-label={t('admin.offers.currency')}
                  />
                  <Input
                    className="w-32"
                    type="number"
                    step="0.01"
                    min={0}
                    value={enMajeur(p.amount_minor)}
                    onChange={(e) => majPrix(i, { amount_minor: enMineur(e.target.value) })}
                    aria-label={t('admin.offers.amount')}
                  />
                  <Input
                    placeholder={t('admin.offers.providerPriceId')}
                    aria-label={t('admin.offers.providerPriceId')}
                    value={p.provider_price_id}
                    onChange={(e) => majPrix(i, { provider_price_id: e.target.value })}
                  />
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 shrink-0 text-destructive"
                    aria-label={t('admin.offers.removePrice')}
                    onClick={() =>
                      setBrouillon((b) => ({
                        ...b,
                        prices: b.prices.filter((_, j) => j !== i),
                      }))
                    }
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
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
          </fieldset>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={brouillon.published}
              onChange={(e) => setBrouillon((b) => ({ ...b, published: e.target.checked }))}
            />
            {t('admin.offers.publish')}
          </label>

          {manquantes.length > 0 && (
            <p
              className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs"
              data-testid="devises-manquantes"
            >
              {t('admin.offers.missingCurrencies', { list: manquantes.join(', ') })}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit">{t('common.save')}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
