import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { paysIso } from '@/shared/iso'
import SearchableSelect from '@/shared/SearchableSelect'
import CountryTaxRates from './CountryTaxRates'
import {
  useCountryProviders, useSaveCountry, useSetCountryProviders,
  type Country, type CountryProvider, type PaymentProvider,
} from './useBillingCatalog'

interface Props {
  pays: Country
  canaux: PaymentProvider[]
  /** Codes deja enregistres : on ne les repropose pas a la creation, un PUT sur
   *  un code existant ecraserait le pays en place sans le dire. */
  codesPris: string[]
  onClose: () => void
}

/**
 * Fiche d'un pays : son libelle, ses devises, ses canaux de paiement.
 *
 * Trois ecritures distinctes derriere un seul formulaire, et leur ORDRE compte :
 * le pays d'abord — les deux autres routes repondent 404 sur un pays inconnu.
 */
export default function CountryEditor({ pays, canaux, codesPris, onClose }: Props) {
  const { t } = useTranslation()
  const existant = Boolean(pays.code)
  const { data: rattachesServeur } = useCountryProviders(pays.code)

  // Un pays neuf n'a rien a lire : ses deux listes partent vides. Un pays
  // existant attend ses donnees — le formulaire n'est monte qu'ensuite, et
  // amorce son etat depuis ses props. Pas d'effet qui recopie le serveur dans
  // l'etat local : la source est choisie une fois, au montage.
  const pret = !existant || rattachesServeur !== undefined

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
      codesPris={codesPris}
      rattachesInitiaux={ordonnes.map((r) => r.provider_slug)}
      onClose={onClose}
    />
  )
}

interface FormProps extends Props {
  rattachesInitiaux: string[]
}

function CountryForm({ pays, canaux, codesPris, rattachesInitiaux, onClose }: FormProps) {
  const { t, i18n } = useTranslation()
  const existant = Boolean(pays.code)
  const [brouillon, setBrouillon] = useState<Country>(pays)
  const [rattaches, setRattaches] = useState<string[]>(rattachesInitiaux)

  const langue = i18n.language
  const cataloguePays = useMemo(
    () => paysIso(langue).filter((p) => existant || !codesPris.includes(p.code)),
    [langue, existant, codesPris],
  )

  const enregistrerPays = useSaveCountry()
  const enregistrerCanaux = useSetCountryProviders(brouillon.code)





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
    try {
      await enregistrerPays.mutateAsync({ ...brouillon, code })
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
              <SearchableSelect
                label={t('admin.billing.countryCode')}
                options={cataloguePays}
                value={brouillon.code}
                // Le code ISO est l'identite : le changer designe un autre pays.
                disabled={existant}
                onSelect={(code) => {
                  const trouve = cataloguePays.find((p) => p.code === code)
                  // Le libelle suit le choix mais reste modifiable : c'est celui
                  // du portail, pas celui du navigateur.
                  setBrouillon((b) => ({ ...b, code, label: trouve?.label ?? b.label }))
                }}
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
