import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import MarkdownField from '@/shared/MarkdownField'
import { devisesIso } from '@/shared/iso'
import { slugifier } from '@/shared/slug'
import { useCurrencies, type PaymentProvider } from './useBillingCatalog'
import {
  useSaveOffer, type HostingType, type Offer, type OfferPrice,
} from './useBillingOffers'

interface Props {
  offre: Offer
  canaux: PaymentProvider[]
  onClose: () => void
}

/** Langue toujours presente : c'est le repli quand la langue du visiteur manque. */
const LANGUE_PIVOT = 'en'
/** Langues proposees a l'ajout. Volontairement courte : on traduit ce qu'on
 *  vend, pas tout ce qui existe. */
const LANGUES_CONNUES = ['en', 'fr', 'de', 'es', 'it', 'nl', 'pt']
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
  const { t, i18n } = useTranslation()
  const existant = Boolean(offre.slug)
  const [brouillon, setBrouillon] = useState<Offer>(offre)
  const [slugManuel, setSlugManuel] = useState(existant)
  const [manquantes, setManquantes] = useState<string[]>([])
  const enregistrer = useSaveOffer()

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

  // Anglais toujours la ; les autres langues s'ajoutent a la demande.
  const langues = useMemo(() => {
    const presentes = new Set([
      LANGUE_PIVOT,
      ...Object.keys(brouillon.titles),
      ...Object.keys(brouillon.descriptions),
    ])
    return [...presentes].sort((a, b) => (a === LANGUE_PIVOT ? -1 : a.localeCompare(b)))
  }, [brouillon.titles, brouillon.descriptions])

  const languesAjoutables = useMemo(
    () => LANGUES_CONNUES.filter((l) => !langues.includes(l)),
    [langues],
  )

  function setLabel(texte: string) {
    // Le slug suit le nom court tant qu'il n'a pas ete saisi a la main, et
    // corrige au passage ce qu'un slug n'accepte pas.
    setBrouillon((b) => ({ ...b, label: texte, slug: slugManuel ? b.slug : slugifier(texte) }))
  }

  function setTitre(langue: string, texte: string) {
    setBrouillon((b) => ({ ...b, titles: { ...b.titles, [langue]: texte } }))
  }

  function setDescription(langue: string, texte: string) {
    setBrouillon((b) => ({ ...b, descriptions: { ...b.descriptions, [langue]: texte } }))
  }

  function ajouterLangue(langue: string) {
    if (!langue) return
    setBrouillon((b) => ({ ...b, titles: { ...b.titles, [langue]: '' } }))
  }

  function retirerLangue(langue: string) {
    setBrouillon((b) => {
      const titles = { ...b.titles }
      const descriptions = { ...b.descriptions }
      delete titles[langue]
      delete descriptions[langue]
      return { ...b, titles, descriptions }
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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="offre-label">{t('admin.offers.shortName')}</Label>
            <Input
              id="offre-label"
              value={brouillon.label}
              onChange={(e) => setLabel(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">{t('admin.offers.shortNameHelp')}</p>
          </div>

          {langues.map((lng) => (
            <fieldset key={lng} className="flex flex-col gap-2 rounded-lg border p-3">
              <legend className="px-1 text-sm font-medium">
                {t('admin.offers.langue', { lng: lng.toUpperCase() })}
                {lng === LANGUE_PIVOT && ` · ${t('admin.offers.langueParDefaut')}`}
              </legend>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`offre-titre-${lng}`}>{t('admin.offers.heading')}</Label>
                <Input
                  id={`offre-titre-${lng}`}
                  value={brouillon.titles[lng] ?? ''}
                  onChange={(e) => setTitre(lng, e.target.value)}
                  required={lng === LANGUE_PIVOT}
                />
              </div>

              <MarkdownField
                id={`offre-description-${lng}`}
                label={t('admin.offers.descriptionField', { lng: lng.toUpperCase() })}
                value={brouillon.descriptions[lng] ?? ''}
                onChange={(texte) => setDescription(lng, texte)}
              />

              {lng !== LANGUE_PIVOT && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="self-end text-xs text-destructive"
                  onClick={() => retirerLangue(lng)}
                >
                  {t('admin.offers.retirerLangue', { lng: lng.toUpperCase() })}
                </Button>
              )}
            </fieldset>
          ))}

          {languesAjoutables.length > 0 && (
            <select
              className="h-9 w-56 rounded-md border border-input bg-transparent px-2 text-sm"
              value=""
              aria-label={t('admin.offers.ajouterLangue')}
              onChange={(e) => ajouterLangue(e.target.value)}
            >
              <option value="">{t('admin.offers.ajouterLangue')}</option>
              {languesAjoutables.map((l) => (
                <option key={l} value={l}>{l.toUpperCase()}</option>
              ))}
            </select>
          )}

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
                // Empile sur mobile : trois champs cote a cote n'y laissaient
                // voir que des amorces tronquees, sans libelle pour dire lequel
                // attend un code et lequel un montant.
                <div
                  key={i}
                  className="flex flex-col gap-2 rounded-md border p-2 sm:flex-row sm:items-end sm:border-0 sm:p-0"
                >
                  <div className="flex flex-col gap-1">
                    <span className="text-xs text-muted-foreground">
                      {t('admin.offers.currency')}
                    </span>
                    <select
                      className="h-9 w-56 rounded-md border border-input bg-transparent px-2 text-sm"
                      value={p.currency}
                      onChange={(e) => majPrix(i, { currency: e.target.value })}
                      aria-label={t('admin.offers.currency')}
                      required
                    >
                      <option value="">—</option>
                      {catalogueDevises
                        // Une devise deja tarifee sur cette offre ne se
                        // repropose pas : deux prix pour une meme devise ne
                        // voudraient rien dire.
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
                    <span className="text-xs text-muted-foreground">
                      {t('admin.offers.amount')}
                    </span>
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
                  onChange={(e) =>
                    setBrouillon((b) => ({ ...b, auto_currencies: e.target.checked }))
                  }
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
                    onChange={(e) =>
                      setBrouillon((b) => ({ ...b, currency_markup: e.target.value }))
                    }
                  />
                </div>
              )}
            </div>
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
