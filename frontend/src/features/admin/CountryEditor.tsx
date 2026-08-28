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
import CountryTaxRates from './CountryTaxRates'
import {
  useCountryProviders, useCurrencies, useSaveCountry, useSetCountryProviders, useSetCurrencies,
  type Country, type CountryCurrency, type CountryProvider, type PaymentProvider,
} from './useBillingCatalog'

interface Props {
  pays: Country
  canaux: PaymentProvider[]
  onClose: () => void
}

/**
 * Fiche d'un pays : son libelle, ses devises, ses canaux de paiement.
 *
 * Trois ecritures distinctes derriere un seul formulaire, et leur ORDRE compte :
 * le pays d'abord — les deux autres routes repondent 404 sur un pays inconnu.
 */
export default function CountryEditor({ pays, canaux, onClose }: Props) {
  const { t } = useTranslation()
  const existant = Boolean(pays.code)
  const { data: devisesServeur } = useCurrencies(pays.code)
  const { data: rattachesServeur } = useCountryProviders(pays.code)

  // Un pays neuf n'a rien a lire : ses deux listes partent vides. Un pays
  // existant attend ses donnees — le formulaire n'est monte qu'ensuite, et
  // amorce son etat depuis ses props. Pas d'effet qui recopie le serveur dans
  // l'etat local : la source est choisie une fois, au montage.
  const pret = !existant || (devisesServeur !== undefined && rattachesServeur !== undefined)

  if (!pret) {
    return (
      <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('admin.billing.editCountry')}</DialogTitle>
            <DialogDescription>{t('admin.billing.countryHelp')}</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        </DialogContent>
      </Dialog>
    )
  }

  const ordonnes = [...(rattachesServeur ?? [])].sort((a, b) => a.priority - b.priority)
  return (
    <CountryForm
      pays={pays}
      canaux={canaux}
      devisesInitiales={devisesServeur ?? []}
      rattachesInitiaux={ordonnes.map((r) => r.provider_slug)}
      onClose={onClose}
    />
  )
}

interface FormProps extends Props {
  devisesInitiales: CountryCurrency[]
  rattachesInitiaux: string[]
}

function CountryForm({ pays, canaux, devisesInitiales, rattachesInitiaux, onClose }: FormProps) {
  const { t } = useTranslation()
  const existant = Boolean(pays.code)
  const [brouillon, setBrouillon] = useState<Country>(pays)
  const [devises, setDevises] = useState<CountryCurrency[]>(devisesInitiales)
  const [rattaches, setRattaches] = useState<string[]>(rattachesInitiaux)

  const enregistrerPays = useSaveCountry()
  const enregistrerDevises = useSetCurrencies(brouillon.code)
  const enregistrerCanaux = useSetCountryProviders(brouillon.code)

  function ajouterDevise() {
    // La premiere devise ajoutee devient le defaut : le serveur en exige
    // exactement un des que la liste n'est pas vide.
    setDevises((d) => [
      ...d,
      { country_code: brouillon.code, currency: '', is_default: d.length === 0 },
    ])
  }

  function majDevise(index: number, valeur: string) {
    setDevises((d) =>
      d.map((x, i) => (i === index ? { ...x, currency: valeur.toUpperCase() } : x)),
    )
  }

  function retirerDevise(index: number) {
    setDevises((d) => {
      const reste = d.filter((_, i) => i !== index)
      // Retirer le defaut laisserait le pays sans devise a proposer : le
      // suivant reprend le role.
      if (reste.length > 0 && !reste.some((x) => x.is_default)) reste[0].is_default = true
      return reste
    })
  }

  function definirDefaut(index: number) {
    setDevises((d) => d.map((x, i) => ({ ...x, is_default: i === index })))
  }

  function basculerCanal(slug: string) {
    setRattaches((r) => (r.includes(slug) ? r.filter((s) => s !== slug) : [...r, slug]))
  }

  async function soumettre(e: React.FormEvent) {
    e.preventDefault()
    const code = brouillon.code.toUpperCase()
    const charge: CountryProvider[] = rattaches.map((slug, i) => ({
      country_code: code,
      provider_slug: slug,
      priority: i,
    }))
    const jeuDevises: CountryCurrency[] = devises
      .filter((d) => d.currency !== '')
      .map((d) => ({ ...d, country_code: code }))

    try {
      await enregistrerPays.mutateAsync({ ...brouillon, code })
      await enregistrerDevises.mutateAsync(jeuDevises)
      await enregistrerCanaux.mutateAsync(charge)
      toast.success(t('admin.billing.countrySaved', { code }))
      onClose()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {existant ? t('admin.billing.editCountry') : t('admin.billing.newCountry')}
          </DialogTitle>
          <DialogDescription>{t('admin.billing.countryHelp')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={soumettre} className="flex flex-col gap-4">
          <div className="grid grid-cols-[8rem_1fr] gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pays-code">{t('admin.billing.countryCode')}</Label>
              <Input
                id="pays-code"
                className="font-mono uppercase"
                value={brouillon.code}
                onChange={(e) =>
                  setBrouillon((b) => ({ ...b, code: e.target.value.toUpperCase() }))
                }
                pattern="^[A-Z]{2}$"
                maxLength={2}
                required
                // Le code ISO est l'identite : le changer designe un autre pays.
                disabled={existant}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pays-label">{t('admin.billing.countryLabel')}</Label>
              <Input
                id="pays-label"
                value={brouillon.label}
                onChange={(e) => setBrouillon((b) => ({ ...b, label: e.target.value }))}
                required
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={brouillon.enabled}
              onChange={(e) => setBrouillon((b) => ({ ...b, enabled: e.target.checked }))}
            />
            {t('admin.billing.countryEnabled')}
          </label>

          <fieldset className="rounded-lg border p-3">
            <legend className="px-1 text-sm font-medium">{t('admin.billing.currencies')}</legend>
            <p className="mb-2 text-xs text-muted-foreground">
              {t('admin.billing.currenciesHelp')}
            </p>
            <div className="flex flex-col gap-2">
              {devises.map((d, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    className="w-24 font-mono uppercase"
                    value={d.currency}
                    onChange={(e) => majDevise(i, e.target.value)}
                    pattern="^[A-Z]{3}$"
                    maxLength={3}
                    aria-label={t('admin.billing.currencyCode')}
                    required
                  />
                  <label className="flex items-center gap-1.5 text-xs">
                    <input
                      type="radio"
                      name="devise-defaut"
                      checked={d.is_default}
                      onChange={() => definirDefaut(i)}
                    />
                    {t('admin.billing.defaultCurrency')}
                  </label>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="ml-auto h-7 w-7 text-destructive"
                    aria-label={t('admin.billing.removeCurrency')}
                    onClick={() => retirerDevise(i)}
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
              onClick={ajouterDevise}
            >
              <Plus className="h-3.5 w-3.5" />
              {t('admin.billing.addCurrency')}
            </Button>
          </fieldset>

          {existant ? (
            <CountryTaxRates code={brouillon.code} />
          ) : (
            <p className="rounded border border-dashed p-3 text-xs text-muted-foreground">
              {t('admin.billing.taxRatesAfterSave')}
            </p>
          )}

          <fieldset className="rounded-lg border p-3">
            <legend className="px-1 text-sm font-medium">{t('admin.billing.attachedProviders')}</legend>
            <p className="mb-2 text-xs text-muted-foreground">
              {t('admin.billing.attachedProvidersHelp')}
            </p>
            {canaux.length === 0 && (
              <p className="text-xs text-muted-foreground">{t('admin.billing.providersEmpty')}</p>
            )}
            <div className="flex flex-col gap-1.5">
              {canaux.map((c) => {
                const rang = rattaches.indexOf(c.slug)
                return (
                  <label key={c.slug} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={rang >= 0}
                      onChange={() => basculerCanal(c.slug)}
                    />
                    <span>{c.label}</span>
                    <span className="font-mono text-xs text-muted-foreground">{c.slug}</span>
                    {rang >= 0 && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        {t('admin.billing.tryOrder', { rank: rang + 1 })}
                      </span>
                    )}
                  </label>
                )
              })}
            </div>
          </fieldset>

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
