import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { OngletProps } from './offerDraft'

/**
 * Combien de temps le forfait dure.
 *
 * Tout forfait est borne : l'essai parce qu'il doit finir, le payant parce
 * qu'un abonnement sans terme ne se facture pas. La duree est en JOURS — une
 * duree exacte, la ou « un mois » n'en est pas une — et c'est d'elle qu'on
 * deduit l'echeance quand un utilisateur souscrit.
 *
 * L'echeance porte un JOUR ET UNE HEURE : l'heure de souscription est
 * conservee, a la minute pres. L'apercu la montre, parce que « 30 jours » ne
 * dit pas a quel moment le service s'arrete.
 */
export default function OfferDurationTab({ brouillon, setBrouillon }: OngletProps) {
  const { t, i18n } = useTranslation()
  const jours = brouillon.duration_days

  // Echeance d'une souscription prise MAINTENANT : c'est ce que l'administrateur
  // cherche a verifier en saisissant une duree.
  const echeance = useMemo(() => {
    if (jours === null) return null
    const fin = new Date(Date.now() + jours * 24 * 60 * 60 * 1000)
    fin.setSeconds(0, 0)
    return new Intl.DateTimeFormat(i18n.language, {
      dateStyle: 'long',
      timeStyle: 'short',
    }).format(fin)
  }, [jours, i18n.language])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="offre-duree">{t('admin.offers.duration')}</Label>
        <div className="flex items-center gap-2">
          <Input
            id="offre-duree"
            className="w-32"
            type="number"
            min={1}
            step={1}
            value={brouillon.duration_days ?? ''}
            onChange={(e) =>
              setBrouillon((b) => ({
                ...b,
                // Vide = non renseignee, et non zero : un forfait de zero jour
                // finirait avant d'avoir commence.
                duration_days: e.target.value === '' ? null : Number(e.target.value),
              }))
            }
            placeholder={t('admin.offers.durationUnset')}
          />
          <span className="text-sm text-muted-foreground">{t('admin.offers.durationUnit')}</span>
        </div>
        <p className="text-xs text-muted-foreground">{t('admin.offers.durationHelp')}</p>
      </div>

      {echeance !== null && (
        <p
          className="rounded-md border border-dashed p-3 text-xs text-muted-foreground"
          data-testid="apercu-echeance"
        >
          {t('admin.offers.durationExample', { jours, echeance })}
        </p>
      )}
    </div>
  )
}
