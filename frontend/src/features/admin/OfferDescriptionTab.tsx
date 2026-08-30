import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import MarkdownField from '@/shared/MarkdownField'
import { slugifier } from '@/shared/slug'
import { LANGUE_PIVOT, LANGUES_CONNUES, type OngletProps } from './offerDraft'
import type { HostingType } from './useBillingOffers'

const HEBERGEMENTS: HostingType[] = ['mutualise', 'dedie']

interface Props extends OngletProps {
  /** Offre deja enregistree : son slug est fige, il sert de cle nulle part ailleurs. */
  existant: boolean
  slugManuel: boolean
  setSlugManuel: (v: boolean) => void
}

/**
 * Ce que l'offre EST : son nom, ses textes clients, ce qu'elle donne droit.
 *
 * Le nom court n'est pas traduit — c'est celui qu'on lit dans l'administration
 * et dans les journaux. Le titre, lui, est montre au client : il se traduit.
 */
export default function OfferDescriptionTab({
  brouillon,
  setBrouillon,
  existant,
  slugManuel,
  setSlugManuel,
}: Props) {
  const { t } = useTranslation()

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
            rows={10}
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
          onChange={(e) => {
            if (e.target.value) {
              setBrouillon((b) => ({ ...b, titles: { ...b.titles, [e.target.value]: '' } }))
            }
          }}
        >
          <option value="">{t('admin.offers.ajouterLangue')}</option>
          {languesAjoutables.map((l) => (
            <option key={l} value={l}>{l.toUpperCase()}</option>
          ))}
        </select>
      )}

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
