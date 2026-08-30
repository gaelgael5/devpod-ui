import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { slugifier } from '@/shared/slug'
import type { OngletProps } from './offerDraft'
import type { HostingType } from './useBillingOffers'

const HEBERGEMENTS: HostingType[] = ['mutualise', 'dedie']

interface Props extends OngletProps {
  /** Offre deja enregistree : son slug est fige, il identifie l'offre partout. */
  existant: boolean
  slugManuel: boolean
  setSlugManuel: (v: boolean) => void
}

/**
 * Ce que l'offre EST, hors de tout texte commercial : son identite et ce
 * qu'elle donne droit.
 *
 * Le nom court n'est pas traduit — c'est celui qu'on lit dans l'administration
 * et dans les journaux. Les titres montres au client vivent dans l'onglet des
 * descriptions, avec leurs traductions.
 */
export default function OfferGeneralTab({
  brouillon,
  setBrouillon,
  existant,
  slugManuel,
  setSlugManuel,
}: Props) {
  const { t } = useTranslation()

  function setLabel(texte: string) {
    // Le slug suit le nom court tant qu'il n'a pas ete saisi a la main, et
    // corrige au passage ce qu'un slug n'accepte pas.
    setBrouillon((b) => ({ ...b, label: texte, slug: slugManuel ? b.slug : slugifier(texte) }))
  }

  function setQuota(champ: 'max_workspaces' | 'max_hosts_dedies', valeur: string) {
    // Vide = illimite, et non zero : zero interdirait tout.
    setBrouillon((b) => ({ ...b, [champ]: valeur === '' ? null : Number(valeur) }))
  }

  return (
    <div className="flex flex-col gap-4">
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

      <div className="grid gap-3 sm:grid-cols-2">
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

      <div className="grid gap-3 sm:grid-cols-2">
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
    </div>
  )
}
