import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Coins, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { devisesIso } from '@/shared/iso'
import { useCurrencies, useSetCurrencies, type Currency } from './useBillingCatalog'

/**
 * Devises acceptees par l'application.
 *
 * Jeu GLOBAL, plus rattache a un pays : ce que la plateforme sait encaisser ne
 * depend pas de l'endroit ou vit l'acheteur. Deux pays de la zone euro n'ont
 * pas chacun « leur » euro.
 *
 * L'enregistrement est explicite plutot qu'a chaque frappe : le serveur
 * remplace le jeu ENTIER et exige exactement un defaut. Envoyer a chaque clic
 * ferait refuser tous les etats intermediaires — ajouter une devise avant de
 * designer le defaut, par exemple.
 */
export default function CurrencyBlock() {
  const { t } = useTranslation()
  const { data: serveur } = useCurrencies()

  // Le formulaire n'est monte qu'une fois les devises la, et amorce son etat
  // depuis ses props : pas d'effet qui recopie le serveur dans l'etat local,
  // sinon un refetch en arriere-plan ecraserait une saisie en cours.
  if (serveur === undefined) {
    return (
      <section className="mt-8">
        <h2 className="mb-1 flex items-center gap-2 font-medium">
          <Coins className="h-4 w-4" />
          {t('admin.billing.currencies')}
        </h2>
        <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
      </section>
    )
  }
  return <CurrencyForm initiales={serveur} />
}

function CurrencyForm({ initiales }: { initiales: Currency[] }) {
  const { t, i18n } = useTranslation()
  const enregistrer = useSetCurrencies()
  const [devises, setBrouillon] = useState<Currency[]>(initiales)
  const [enregistrees, setEnregistrees] = useState<Currency[]>(initiales)
  const catalogue = useMemo(() => devisesIso(i18n.language), [i18n.language])

  const modifie = JSON.stringify(devises) !== JSON.stringify(enregistrees)
  const restantes = catalogue.filter((c) => !devises.some((d) => d.code === c.code))

  function ajouter(code: string) {
    if (!code) return
    setBrouillon((b) => [
      ...b,
      // La premiere devise ajoutee devient le defaut : le serveur en exige
      // exactement un des que la liste n'est pas vide.
      { code, enabled: true, is_default: b.length === 0 },
    ])
  }

  function retirer(code: string) {
    setBrouillon((b) => {
      const reste = b.filter((d) => d.code !== code)
      // Retirer le defaut laisserait le portail sans devise a proposer : la
      // premiere active reprend le role.
      if (reste.length > 0 && !reste.some((d) => d.is_default)) {
        const reprise = reste.find((d) => d.enabled) ?? reste[0]
        reprise.is_default = true
      }
      return reste
    })
  }

  function basculerActive(code: string) {
    setBrouillon((b) => b.map((d) => (d.code === code ? { ...d, enabled: !d.enabled } : d)))
  }

  function definirDefaut(code: string) {
    // Le defaut doit etre encaissable : le designer reactive la devise.
    setBrouillon((b) =>
      b.map((d) =>
        d.code === code ? { ...d, is_default: true, enabled: true } : { ...d, is_default: false },
      ),
    )
  }

  function soumettre() {
    toast.promise(enregistrer.mutateAsync(devises), {
      loading: '…',
      success: (sauves) => {
        setEnregistrees(sauves)
        return t('admin.billing.currenciesSaved')
      },
      error: (err: Error) => err.message,
    })
  }

  return (
    <section className="mt-8">
      <div className="mb-3 flex items-start justify-between gap-4">
        <h2 className="flex items-center gap-2 font-medium">
          <Coins className="h-4 w-4" />
          {t('admin.billing.currencies')}
        </h2>
        <Button
          size="sm"
          onClick={soumettre}
          disabled={!modifie || enregistrer.isPending}
          className="shrink-0"
        >
          {t('common.save')}
        </Button>
      </div>
      <p className="mb-3 text-sm text-muted-foreground">{t('admin.billing.currenciesHelp')}</p>

      {devises.length === 0 && (
        <p className="rounded border border-dashed p-6 text-center text-sm text-muted-foreground">
          {t('admin.billing.currenciesEmpty')}
        </p>
      )}

      <div className="flex flex-col gap-2">
        {devises.map((d) => (
          <div
            key={d.code}
            className="flex flex-wrap items-center gap-3 rounded-lg border p-3"
            data-testid={`devise-${d.code}`}
          >
            <span className="font-mono text-sm font-medium">{d.code}</span>
            <span className="text-sm text-muted-foreground">
              {catalogue.find((c) => c.code === d.code)?.label ?? d.code}
            </span>
            <label className="flex items-center gap-1.5 text-xs">
              <input type="checkbox" checked={d.enabled} onChange={() => basculerActive(d.code)} />
              {t('admin.billing.currencyEnabled')}
            </label>
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="radio"
                name="devise-defaut"
                checked={d.is_default}
                onChange={() => definirDefaut(d.code)}
              />
              {t('admin.billing.defaultCurrency')}
            </label>
            <Button
              size="icon"
              variant="ghost"
              className="ml-auto h-7 w-7 text-destructive"
              aria-label={t('admin.billing.removeCurrency')}
              onClick={() => retirer(d.code)}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <Plus className="h-3.5 w-3.5 text-muted-foreground" />
        <select
          className="h-9 w-64 rounded-md border border-input bg-transparent px-2 text-sm"
          value=""
          aria-label={t('admin.billing.addCurrency')}
          onChange={(e) => ajouter(e.target.value)}
        >
          <option value="">{t('admin.billing.addCurrency')}</option>
          {restantes.map((c) => (
            <option key={c.code} value={c.code}>
              {c.code} · {c.label}
            </option>
          ))}
        </select>
      </div>
    </section>
  )
}
