import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import MarkdownField from '@/shared/MarkdownField'
import { LANGUE_PIVOT, LANGUES_CONNUES, type OngletProps } from './offerDraft'

/**
 * Les textes montres au CLIENT, langue par langue.
 *
 * L'anglais est toujours la : c'est le repli quand la langue du visiteur
 * manque. Les autres s'ajoutent a la demande — on traduit ce qu'on vend, pas
 * tout ce qui existe.
 */
export default function OfferDescriptionTab({ brouillon, setBrouillon }: OngletProps) {
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

  return (
    <div className="flex flex-col gap-4">
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

    </div>
  )
}
