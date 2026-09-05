import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Quotas } from './ForfaitsPage'
import { formaterMontant } from './montant'
import { useOffresPubliques, type OffrePubliee } from './useOffresPubliques'
import {
  useMesSouscriptions,
  useMonHistorique,
  useReprendre,
  type EntreeHistorique,
  type Souscription,
} from './useMonAbonnement'

/**
 * L'abonnement, vu par son titulaire : ce qu'il paie, jusqu'à quand, et ce qui
 * s'est passé.
 *
 * Trois choix qui structurent la page :
 *
 * - **le prix affiché est l'INSTANTANÉ de la souscription**, jamais le
 *   catalogue d'aujourd'hui — l'abonné garde le prix auquel il a souscrit ;
 * - **l'historique vient filtré du serveur** (ses achats, rien de
 *   l'exploitation) : la page n'a aucun filtrage à refaire, donc aucun à rater ;
 * - **« changer de forfait » renvoie vers la page publique** — souscrire un
 *   autre forfait est légitime et fonctionne aujourd'hui. Le changement
 *   DIFFÉRÉ (prise d'effet au renouvellement, migration automatique) est
 *   décidé mais pas encore cadré techniquement : la page n'en promet rien
 *   tant qu'il n'existe pas, exactement comme la mention « sans engagement ».
 */

function _date(iso: string, langue: string): string {
  return new Intl.DateTimeFormat(langue, { dateStyle: 'short' }).format(new Date(iso))
}

function CarteAbonnement({
  souscription,
  offre,
}: {
  souscription: Souscription
  offre: OffrePubliee | undefined
}) {
  const { t, i18n } = useTranslation()
  const langue = i18n.language.split('-')[0]
  // L'offre peut avoir quitté le catalogue publié : l'abonnement, lui, reste —
  // le slug identifie encore ce qui a été souscrit.
  const titre = offre?.titles[langue] ?? offre?.titles.en ?? souscription.offer_slug

  return (
    <article
      data-testid={`abonnement-${souscription.id}`}
      className="flex flex-col gap-3 rounded-lg border p-5"
    >
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold">{titre}</h3>
        <span className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground">
          {t(`abonnement.etat.${souscription.state}`)}
        </span>
      </header>
      <p className="text-xl font-semibold">
        {souscription.amount_minor === 0
          ? t('forfaits.free')
          : formaterMontant(souscription.amount_minor, souscription.currency, i18n.language)}
      </p>
      {offre && <Quotas offre={offre} />}
      {souscription.ends_at && (
        <p className="text-sm text-muted-foreground">
          {t('abonnement.echeance', { date: _date(souscription.ends_at, i18n.language) })}
        </p>
      )}
      {souscription.state === 'resilie' && <BoutonReprendre souscription={souscription} />}
    </article>
  )
}

/** La reprise : un acte commercial neuf — le prix affiché sera celui du jour,
 * pas l'instantané d'hier, et le bouton le dit avant le clic. */
function BoutonReprendre({ souscription }: { souscription: Souscription }) {
  const { t } = useTranslation()
  const reprendre = useReprendre()

  function onClick() {
    reprendre.mutate(souscription.id, {
      onSuccess: () => toast.success(t('abonnement.reprisePartie')),
      onError: (err: Error) => toast.error(err.message),
    })
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div>
        <Button variant="outline" onClick={onClick} disabled={reprendre.isPending}>
          {reprendre.isPending ? '…' : t('abonnement.reprendre')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t('abonnement.reprendreHint')}</p>
    </div>
  )
}

function Historique({ entrees }: { entrees: EntreeHistorique[] }) {
  const { t, i18n } = useTranslation()
  if (entrees.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('abonnement.historiqueVide')}</p>
  }
  return (
    <ul data-testid="historique-achats" className="flex flex-col divide-y rounded-lg border">
      {entrees.map((e) => (
        <li key={e.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
          <span className="w-24 shrink-0 text-xs text-muted-foreground">
            {_date(e.occurred_at, i18n.language)}
          </span>
          <span className="min-w-0 flex-1">{t(`abonnement.evenement.${e.kind}`)}</span>
          {e.offer_slug && (
            <span className="truncate font-mono text-xs text-muted-foreground">
              {e.offer_slug}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

export default function AbonnementPage() {
  const { t } = useTranslation()
  const { data: souscriptions, isLoading } = useMesSouscriptions()
  const { data: historique } = useMonHistorique()
  const { data: offres } = useOffresPubliques()

  const parSlug = new Map((offres ?? []).map((o) => [o.slug, o]))
  const ouverts = (souscriptions ?? []).filter((s) => s.state !== 'resilie')
  const termines = (souscriptions ?? []).filter((s) => s.state === 'resilie')

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8 p-6">
      <header className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">{t('abonnement.title')}</h1>
        <Link
          to="/forfaits"
          className="inline-flex h-9 items-center rounded-md border px-4 text-sm font-medium transition-colors hover:bg-muted"
        >
          {t('abonnement.voirForfaits')}
        </Link>
      </header>

      {isLoading && <p className="text-muted-foreground">{t('common.loading')}</p>}

      {!isLoading && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">{t('abonnement.courant')}</h2>
          {ouverts.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('abonnement.aucunOuvert')}</p>
          )}
          {ouverts.map((s) => (
            <CarteAbonnement key={s.id} souscription={s} offre={parSlug.get(s.offer_slug)} />
          ))}
        </section>
      )}

      {termines.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">{t('abonnement.termines')}</h2>
          {termines.map((s) => (
            <CarteAbonnement key={s.id} souscription={s} offre={parSlug.get(s.offer_slug)} />
          ))}
        </section>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">{t('abonnement.historique')}</h2>
        <Historique entrees={historique ?? []} />
      </section>
    </div>
  )
}
