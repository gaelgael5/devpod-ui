import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import Markdown from '@/shared/Markdown'
import { ApiError } from '@/shared/api/client'
import { useOffresPubliques } from './useOffresPubliques'
import { useContexteSouscription, useSouscrire } from './useSouscription'

/**
 * Écran d'engagement : ce à quoi le client souscrit, avant de le faire.
 *
 * Il ne prend AUCUN paiement — cette étape viendra. Une offre gratuite se
 * souscrit donc ici de bout en bout ; une offre payante crée l'abonnement et
 * s'arrête au seuil du paiement.
 *
 * Deux partis pris d'écran :
 *
 * - **le bouton n'est actif qu'après une case cochée.** L'engagement doit être
 *   un geste, pas la conséquence d'un clic mal placé ;
 * - **on n'annonce pas « sans engagement ».** La résiliation n'existe pas
 *   encore (étape 8 de l'ordre d'exécution) : promettre une sortie qui n'est
 *   pas là, sur la page même où le client s'engage, serait une promesse fausse.
 *   L'emplacement est prévu, le texte viendra avec le bouton de sortie.
 */
export default function SouscriptionPage() {
  const { t, i18n } = useTranslation()
  const { slug = '' } = useParams()

  const { data: offres, isLoading: chargeOffres } = useOffresPubliques()
  const { data: contexte, isLoading: chargeContexte } = useContexteSouscription()
  const souscrire = useSouscrire()

  // Le pré-remplissage est DÉRIVÉ, pas posé dans un effet : on ne mémorise que
  // ce que l'utilisateur a choisi, et le défaut se recalcule tant qu'il n'a
  // rien choisi. Un effet qui écrit l'état écraserait son choix au premier
  // rafraîchissement du contexte, et il faudrait s'en garder à la main.
  const [paysChoisi, setPaysChoisi] = useState<string | null>(null)
  const [deviseChoisie, setDeviseChoisie] = useState<string | null>(null)
  const [confirme, setConfirme] = useState(false)

  const pays = paysChoisi ?? contexte?.pays_devine ?? contexte?.pays[0]?.code ?? ''
  const devise = deviseChoisie ?? contexte?.devise_par_defaut ?? contexte?.devises[0] ?? ''

  const offre = offres?.find((o) => o.slug === slug)

  if (chargeOffres || chargeContexte) {
    return <p className="p-6 text-muted-foreground">{t('forfaits.loading')}</p>
  }
  if (!offre) {
    return (
      <div className="flex flex-col items-start gap-4 p-6">
        <p className="text-muted-foreground">{t('souscription.offreIntrouvable')}</p>
        <Link to="/forfaits" className="text-sm underline">
          {t('souscription.retour')}
        </Link>
      </div>
    )
  }

  if (souscrire.isSuccess) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col items-start gap-4 p-6">
        <h1 className="text-2xl font-semibold tracking-tight">{t('souscription.merciTitre')}</h1>
        <p className="text-muted-foreground">{t('souscription.merciCorps')}</p>
        <Link
          to="/workspaces"
          className="inline-flex h-10 items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground"
        >
          {t('souscription.versWorkspaces')}
        </Link>
      </div>
    )
  }

  const langue = i18n.language.split('-')[0]
  const titre = offre.titles[langue] ?? offre.titles.en ?? offre.slug
  const description = offre.descriptions[langue] ?? offre.descriptions.en ?? ''

  function envoyer() {
    souscrire.mutate({ offer_slug: slug, country_code: pays, currency: devise })
  }

  // Le refus du serveur est rédigé pour être lu : on l'affiche tel quel plutôt
  // que de le traduire en « une erreur est survenue ».
  const refus =
    souscrire.error instanceof ApiError ? souscrire.error.message : souscrire.error ? t('errors.generic') : null

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <Link to="/forfaits" className="text-sm text-muted-foreground hover:text-foreground">
        {t('souscription.retour')}
      </Link>

      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t('souscription.titre')}</h1>
        <h2 className="text-lg font-medium">
          <Markdown inline>{titre}</Markdown>
        </h2>
        {description && (
          <Markdown className="text-sm text-muted-foreground">{description}</Markdown>
        )}
      </header>

      <section className="flex flex-col gap-3 rounded-lg border p-4">
        <h3 className="text-sm font-medium">{t('souscription.recapTitre')}</h3>
        <dl className="flex flex-col gap-1 text-sm text-muted-foreground">
          {offre.duration_days !== null && (
            <div className="flex justify-between gap-4">
              <dt>{t('souscription.duree')}</dt>
              <dd>{t('forfaits.duration', { value: offre.duration_days })}</dd>
            </div>
          )}
          <div className="flex justify-between gap-4">
            <dt>{t('souscription.auTerme')}</dt>
            <dd>{t(offre.tacite_reconduction ? 'forfaits.renews' : 'forfaits.endsAtTerm')}</dd>
          </div>
        </dl>
      </section>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1.5 text-sm">
          {t('souscription.pays')}
          <select
            value={pays}
            onChange={(e) => setPaysChoisi(e.target.value)}
            className="h-9 rounded-md border bg-background px-2 text-sm"
          >
            {contexte?.pays.map((p) => (
              <option key={p.code} value={p.code}>
                {p.label}
              </option>
            ))}
          </select>
          <span className="text-xs text-muted-foreground">{t('souscription.paysAide')}</span>
        </label>

        <label className="flex flex-col gap-1.5 text-sm">
          {t('souscription.devise')}
          <select
            value={devise}
            onChange={(e) => setDeviseChoisie(e.target.value)}
            className="h-9 rounded-md border bg-background px-2 text-sm"
          >
            {contexte?.devises.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="flex items-start gap-2 rounded-lg border p-4 text-sm">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={confirme}
          onChange={(e) => setConfirme(e.target.checked)}
        />
        <span>{t('souscription.confirmation')}</span>
      </label>

      {refus && (
        <p role="alert" className="rounded-md border border-destructive/50 p-3 text-sm">
          {refus}
        </p>
      )}

      <Button
        onClick={envoyer}
        // Deux gardes distinctes : la case cochée, et la soumission en cours.
        // Sans la seconde, un double-clic crée deux abonnements.
        disabled={!confirme || !pays || !devise || souscrire.isPending}
        className="self-start"
      >
        {t(souscrire.isPending ? 'souscription.envoi' : 'souscription.valider')}
      </Button>
    </div>
  )
}
