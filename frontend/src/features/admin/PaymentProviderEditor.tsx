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
import {
  useSaveProvider, useSystemSecrets, type PaymentProvider, type SystemSecret, type TaxMode,
} from './useBillingCatalog'

interface Props {
  canal: PaymentProvider
  onClose: () => void
}

const MODES: TaxMode[] = ['manuel', 'automatique']

//: Miroir de `PROVIDER_CONFIG_MODELS` cote serveur : les kinds dont la config a
//: une forme connue recoivent un formulaire type ; les autres gardent le
//: cle/valeur libre.
const KINDS_TYPES = new Set(['stripe'])

/**
 * Config d'un canal Stripe — les DEUX champs de `StripeConfig`, nommes.
 *
 * Le cle/valeur libre faisait deviner les clefs a l'admin : la faute de frappe
 * etait refusee par le serveur (`extra="forbid"`), mais rien ne disait quoi
 * saisir. Le secret de webhook se DESIGNE comme la cle API — jamais de valeur
 * `whsec_…` en clair ici.
 */
function StripeConfigFields({
  config,
  secrets,
  onChange,
}: {
  config: Record<string, string>
  secrets: SystemSecret[]
  onChange: (config: Record<string, string>) => void
}) {
  const { t } = useTranslation()

  return (
    <fieldset className="rounded-lg border p-3">
      <legend className="px-1 text-sm font-medium">{t('admin.billing.config')}</legend>
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="stripe-account">{t('admin.billing.stripeAccountId')}</Label>
          <Input
            id="stripe-account"
            className="font-mono"
            value={config.account_id ?? ''}
            placeholder="acct_…"
            onChange={(e) => onChange({ ...config, account_id: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">{t('admin.billing.stripeAccountHelp')}</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="stripe-whsec">{t('admin.billing.stripeWebhookSecret')}</Label>
          <select
            id="stripe-whsec"
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
            value={config.webhook_secret_slug ?? ''}
            onChange={(e) => onChange({ ...config, webhook_secret_slug: e.target.value })}
          >
            <option value="">{t('admin.billing.noSecret')}</option>
            {secrets.map((s) => (
              <option key={s.slug} value={s.slug}>{s.label || s.slug}</option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            {t('admin.billing.stripeWebhookSecretHelp')}
          </p>
        </div>
      </div>
    </fieldset>
  )
}

/**
 * Fiche d'un canal de paiement.
 *
 * Deux choses que ce formulaire ne fait JAMAIS : saisir une cle API — on
 * DESIGNE un secret existant par son slug — et deviner le mode de taxe, qui
 * decide si la plateforme envoie du HT ou du TTC au provider.
 */
export default function PaymentProviderEditor({ canal, onClose }: Props) {
  const { t } = useTranslation()
  const existant = Boolean(canal.slug)
  const [brouillon, setBrouillon] = useState<PaymentProvider>(canal)
  const [slugManuel, setSlugManuel] = useState(existant)
  const { data: secrets = [] } = useSystemSecrets()
  const enregistrer = useSaveProvider()

  const entrees = Object.entries(brouillon.config)

  function setLabel(label: string) {
    setBrouillon((b) => ({ ...b, label, slug: slugManuel ? b.slug : slugifier(label) }))
  }

  function majCle(ancienne: string, nouvelle: string) {
    setBrouillon((b) => {
      const config: Record<string, string> = {}
      for (const [k, v] of Object.entries(b.config)) config[k === ancienne ? nouvelle : k] = v
      return { ...b, config }
    })
  }

  function majValeur(cle: string, valeur: string) {
    setBrouillon((b) => ({ ...b, config: { ...b.config, [cle]: valeur } }))
  }

  function retirerCle(cle: string) {
    setBrouillon((b) => {
      const config = { ...b.config }
      delete config[cle]
      return { ...b, config }
    })
  }

  function soumettre(e: React.FormEvent) {
    e.preventDefault()
    // Une cle vide ne designe rien : le serveur la refuserait, autant ne pas
    // l'envoyer.
    const config = Object.fromEntries(entrees.filter(([k]) => k.trim() !== ''))
    toast.promise(enregistrer.mutateAsync({ ...brouillon, config }), {
      loading: '…',
      success: () => {
        onClose()
        return t('admin.billing.providerSaved', { slug: brouillon.slug })
      },
      error: (err: Error) => err.message,
    })
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {existant ? t('admin.billing.editProvider') : t('admin.billing.newProvider')}
          </DialogTitle>
          <DialogDescription>{t('admin.billing.providerHelp')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={soumettre} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="canal-label">{t('admin.billing.providerLabel')}</Label>
            <Input
              id="canal-label"
              value={brouillon.label}
              onChange={(e) => setLabel(e.target.value)}
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="canal-slug">{t('admin.billing.providerSlug')}</Label>
              <Input
                id="canal-slug"
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
              <p className="text-xs text-muted-foreground">{t('admin.billing.slugHelp')}</p>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="canal-kind">{t('admin.billing.providerKind')}</Label>
              <select
                id="canal-kind"
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                value={brouillon.kind}
                onChange={(e) =>
                  setBrouillon((b) => ({ ...b, kind: e.target.value as PaymentProvider['kind'] }))
                }
              >
                <option value="stripe">stripe</option>
              </select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="canal-tax">{t('admin.billing.taxModeLabel')}</Label>
            <select
              id="canal-tax"
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
              value={brouillon.tax_mode}
              onChange={(e) =>
                setBrouillon((b) => ({ ...b, tax_mode: e.target.value as TaxMode }))
              }
            >
              {MODES.map((m) => (
                <option key={m} value={m}>{t(`admin.billing.taxMode.${m}`)}</option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              {t(`admin.billing.taxModeHelp.${brouillon.tax_mode}`)}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="canal-secret">{t('admin.billing.secretSlug')}</Label>
            <select
              id="canal-secret"
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
              value={brouillon.secret_slug}
              onChange={(e) => setBrouillon((b) => ({ ...b, secret_slug: e.target.value }))}
            >
              <option value="">{t('admin.billing.noSecret')}</option>
              {secrets.map((s) => (
                <option key={s.slug} value={s.slug}>{s.label || s.slug}</option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">{t('admin.billing.secretHelp')}</p>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={brouillon.enabled}
              onChange={(e) => setBrouillon((b) => ({ ...b, enabled: e.target.checked }))}
            />
            {t('admin.billing.providerEnabled')}
          </label>

          {KINDS_TYPES.has(brouillon.kind) ? (
            <StripeConfigFields
              config={brouillon.config}
              secrets={secrets}
              onChange={(config) => setBrouillon((b) => ({ ...b, config }))}
            />
          ) : (
          <fieldset className="rounded-lg border p-3">
            <legend className="px-1 text-sm font-medium">{t('admin.billing.config')}</legend>
            <p className="mb-2 text-xs text-muted-foreground">{t('admin.billing.configHelp')}</p>
            <div className="flex flex-col gap-2">
              {entrees.map(([cle, valeur], i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    className="w-1/3 font-mono"
                    value={cle}
                    onChange={(e) => majCle(cle, e.target.value)}
                    aria-label={t('admin.billing.configKey')}
                  />
                  <Input
                    value={valeur}
                    onChange={(e) => majValeur(cle, e.target.value)}
                    aria-label={t('admin.billing.configValue')}
                  />
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 shrink-0 text-destructive"
                    aria-label={t('admin.billing.removeConfigKey')}
                    onClick={() => retirerCle(cle)}
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
              onClick={() => majValeur('', '')}
            >
              <Plus className="h-3.5 w-3.5" />
              {t('admin.billing.addConfigKey')}
            </Button>
          </fieldset>
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
