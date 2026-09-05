import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useOnboarding } from './useOnboarding'

/**
 * Le parcours guidé à la première connexion (fiche 849978e7).
 *
 * Monté une fois dans l'AppShell, il se pilote sur l'état serveur. Trois règles
 * de la fiche que le rendu tient :
 *
 * - **pause silencieuse** : la bulle ne s'affiche que sur la page de l'étape
 *   courante ; ailleurs, seuls les contrôles globaux restent (jamais de
 *   redirection forcée) ;
 * - **Close ≠ Next** : Close masque la bulle POUR CETTE SESSION (état local),
 *   le parcours reprendra à la même étape à la prochaine connexion ; Next
 *   avance l'index persisté ;
 * - **Réouvrir hors séquence** : si on n'est pas sur la bonne page, un message
 *   générique dit où aller, sans y emmener de force.
 */
export default function OnboardingOverlay() {
  const { t } = useTranslation()
  const { etapeCourante, surLaPage, index, total, actif, suivant, desactiver } = useOnboarding()
  // « Fermé pour cette session » : local, non persisté — la reprise se fait au
  // prochain chargement, exactement ce que Close promet.
  const [fermeSession, setFermeSession] = useState(false)

  if (!actif || !etapeCourante) return null

  const bulleVisible = surLaPage && !fermeSession

  function reouvrir() {
    setFermeSession(false)
    if (!surLaPage) {
      // Hors séquence : on ne redirige pas, on dit où aller (décision fiche).
      toast.info(
        t('onboarding.horsSequence', {
          page: t(`onboarding.steps.${etapeCourante!.key}.title`),
        }),
      )
    }
  }

  return (
    <>
      {/* Contrôles globaux, accessibles depuis n'importe quelle page. */}
      <div className="fixed right-4 top-3 z-50 flex gap-2">
        <Button size="sm" variant="outline" onClick={reouvrir}>
          {t('onboarding.reouvrir')}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-muted-foreground"
          onClick={desactiver}
        >
          {t('onboarding.desactiver')}
        </Button>
      </div>

      {bulleVisible && (
        <div
          role="dialog"
          aria-label={t('onboarding.aria')}
          data-testid="onboarding-bulle"
          className="fixed bottom-6 right-6 z-50 w-80 rounded-lg border bg-background p-4 shadow-lg"
        >
          <p className="text-xs text-muted-foreground">
            {t('onboarding.progression', { index: index + 1, total })}
          </p>
          <h3 className="mt-1 text-sm font-semibold">
            {t(`onboarding.steps.${etapeCourante.key}.title`)}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {t(`onboarding.steps.${etapeCourante.key}.body`)}
          </p>
          <div className="mt-3 flex justify-between gap-2">
            <Button size="sm" variant="ghost" onClick={() => setFermeSession(true)}>
              {t('onboarding.fermer')}
            </Button>
            <Button size="sm" onClick={suivant}>
              {index + 1 >= total ? t('onboarding.terminer') : t('onboarding.suivant')}
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
