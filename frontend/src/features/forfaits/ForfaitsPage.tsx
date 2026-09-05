import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import LanguageSelect from '@/shared/nav/LanguageSelect'
import Markdown from '@/shared/Markdown'
import { useOptionalSession } from '@/features/auth/useOptionalSession'
import { formaterMontant } from './montant'
import { useOffresPubliques, type OffrePubliee } from './useOffresPubliques'

/**
 * Page publique des forfaits : elle AFFICHE les offres paramétrées dans
 * l'application, et rien de plus.
 *
 * Elle ne souscrit pas, ne calcule pas de taxe et ne devine pas le pays du
 * visiteur. Le montant est montré **tel qu'il est saisi**, étiqueté HT ou TTC :
 * sans pays connu, un TTC calculé serait un prix faux, et un prix faux est pire
 * qu'un prix absent.
 *
 * ⚠️ Textes PROVISOIRES, comme sur la landing — le contenu définitif fait
 * l'objet d'un ticket séparé.
 */


function Prix({ offre }: { offre: OffrePubliee }) {
  const { t, i18n } = useTranslation()

  if (offre.is_free) {
    return <p className="text-2xl font-semibold">{t('forfaits.free')}</p>
  }
  // Ni prix dans la devise par défaut, ni devise désignée : on ne montre pas de
  // montant plutôt que d'en convertir un depuis une autre devise.
  if (offre.amount_minor === null || offre.currency === null) {
    return <p className="text-sm text-muted-foreground">{t('forfaits.priceUnavailable')}</p>
  }
  return (
    <div>
      <p className="text-2xl font-semibold">
        {formaterMontant(offre.amount_minor, offre.currency, i18n.language)}
      </p>
      <p className="text-xs text-muted-foreground">
        {t(offre.prices_include_tax ? 'forfaits.taxIncluded' : 'forfaits.taxExcluded')}
      </p>
    </div>
  )
}

export function Quotas({ offre }: { offre: OffrePubliee }) {
  const { t } = useTranslation()
  // `null` = illimité, pour les deux quotas. Un plafond absent n'est pas zéro.
  const illimite = t('forfaits.unlimited')
  const valeur = (quota: number | null) => (quota === null ? illimite : String(quota))

  // Les deux types d'hébergement ne décrivent pas la même chose avec les mêmes
  // champs : en dédié `max_workspaces` est le plafond par machine résolu par le
  // serveur (capacité du profil de host, bornée par le quota de l'offre), en
  // mutualisé c'est le quota personnel du souscripteur sur le pool.
  //
  // En dédié, `null` = NON RENSEIGNÉ, pas illimité — une machine « illimitée »
  // n'existe pas. On tait la ligne plutôt que de promettre faux.
  const lignes =
    offre.hosting_type === 'dedie'
      ? [
          t('forfaits.dedicatedHosts', { value: valeur(offre.max_hosts_dedies) }),
          ...(offre.max_workspaces !== null
            ? [t('forfaits.hostCapacity', { value: String(offre.max_workspaces) })]
            : []),
        ]
      : [t('forfaits.sharedQuota', { value: valeur(offre.max_workspaces) })]

  if (offre.duration_days !== null) {
    lignes.push(t('forfaits.duration', { value: offre.duration_days }))
    // Ce qui advient AU TERME est une information matérielle avant de
    // s'engager : elle dit si le client sera prélevé à nouveau. On l'affiche
    // dans les deux cas — « ne se reconduit pas » rassure autant que
    // « se reconduit » avertit, et un silence laisserait deviner.
    lignes.push(
      t(offre.tacite_reconduction ? 'forfaits.renews' : 'forfaits.endsAtTerm'),
    )
  }
  if (offre.une_par_compte) {
    lignes.push(t('forfaits.oncePerAccount'))
  }

  return (
    <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
      {lignes.map((ligne) => (
        <li key={ligne}>{ligne}</li>
      ))}
    </ul>
  )
}

function Carte({ offre, connecte }: { offre: OffrePubliee; connecte: boolean }) {
  const { t, i18n } = useTranslation()
  // Le titre vient de l'offre, pas des clés i18n : c'est l'administrateur qui
  // l'a saisi, langue par langue. À défaut de traduction, le slug reste
  // identifiable — mieux qu'une carte anonyme.
  const langue = i18n.language.split('-')[0]
  const titre = offre.titles[langue] ?? offre.titles.en ?? offre.slug
  const description = offre.descriptions[langue] ?? offre.descriptions.en ?? ''

  // Titre ET description sont saisis en markdown par l'administrateur (cf.
  // `MarkdownField` cote admin) : les afficher bruts montrait les `**` au
  // visiteur. Le titre est rendu INLINE pour ne pas glisser un bloc dans le h2.
  return (
    <article className="flex flex-col gap-4 rounded-lg border p-6">
      <header className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">
          <Markdown inline>{titre}</Markdown>
        </h2>
        {description && (
          <Markdown className="text-sm text-muted-foreground">{description}</Markdown>
        )}
      </header>
      <Prix offre={offre} />
      <Quotas offre={offre} />
      {/* Un visiteur anonyme ne peut pas souscrire : on l'envoie se connecter
          plutot que de lui laisser decouvrir un 401 apres avoir tout rempli. */}
      <Link
        to={connecte ? `/forfaits/${offre.slug}` : '/auth/login'}
        className="mt-auto inline-flex h-10 items-center justify-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        {t('forfaits.choisir')}
      </Link>
    </article>
  )
}

/**
 * Page d'origine transmise par la navigation, ou `null`.
 *
 * L'etat de navigation est manipulable (history.pushState) : seul un chemin
 * interne est accepte. `//` est exclu explicitement — un href `//evil.example`
 * est une URL protocol-relative, donc une sortie du site.
 */
function origineDe(state: unknown): string | null {
  if (typeof state !== 'object' || state === null) return null
  const from = (state as Record<string, unknown>).from
  if (typeof from !== 'string' || !from.startsWith('/') || from.startsWith('//')) return null
  return from
}

export default function ForfaitsPage() {
  const { t } = useTranslation()
  const { state } = useLocation()
  const { data: offres, isLoading, isError } = useOffresPubliques()
  // La page sert deux publics : un visiteur qui compare avant de creer un
  // compte, et un abonne qui vient voir ce qui existe. Le contenu est le meme —
  // le catalogue publie — mais l'en-tete ne peut pas l'etre : proposer « Se
  // connecter » a quelqu'un de deja connecte, et le renvoyer vers la page de
  // presentation plutot que vers ses workspaces, serait absurde.
  //
  // `useOptionalSession` et non `useSession` : cette page reste PUBLIQUE, et un
  // 401 y signifie « anonyme », pas « erreur ». Voir son commentaire.
  const { data: session } = useOptionalSession()
  const connecte = Boolean(session)

  // Un visiteur peut arriver de plusieurs endroits — le menu profil, la barre
  // de section admin, une URL directe. Quand la navigation transmet l'origine,
  // le retour y renvoie ; sinon on retombe sur la destination par defaut.
  const origine = origineDe(state)

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between px-6 py-4">
        <Link
          to={origine ?? (connecte ? '/workspaces' : '/')}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          {origine ? t('forfaits.back') : t(connecte ? 'forfaits.backApp' : 'forfaits.backHome')}
        </Link>
        <div className="flex items-center gap-3">
          {!connecte && (
            <Link
              to="/auth/login"
              className="inline-flex h-9 items-center rounded-md border px-4 text-sm font-medium transition-colors hover:bg-muted"
            >
              {t('landing.ctaLogin')}
            </Link>
          )}
          {/* Le selecteur ne persiste pas : un visiteur anonyme n'a pas de
              compte ou ranger son choix, et un abonne a le sien dans son
              profil. Voir `useLanguageChoice`. */}
          <LanguageSelect persist={false} />
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-12">
        <h1 className="text-3xl font-semibold tracking-tight">{t('forfaits.title')}</h1>

        {isLoading && <p className="text-muted-foreground">{t('forfaits.loading')}</p>}
        {isError && <p className="text-muted-foreground">{t('forfaits.loadFailed')}</p>}
        {offres && offres.length === 0 && (
          <p className="text-muted-foreground">{t('forfaits.none')}</p>
        )}

        {offres && offres.length > 0 && (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {offres.map((offre) => (
              <Carte key={offre.slug} offre={offre} connecte={connecte} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
