import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import LanguageSelect from '@/shared/nav/LanguageSelect'
import Markdown from '@/shared/Markdown'
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

/**
 * Montant lisible depuis des unités mineures.
 *
 * Le nombre de décimales vient d'`Intl` et non d'une division par 100 : le yen
 * n'a pas de sous-unité, et diviser aveuglément afficherait un prix cent fois
 * trop petit.
 */
function formaterMontant(minor: number, devise: string, langue: string): string {
  const format = new Intl.NumberFormat(langue, { style: 'currency', currency: devise })
  const decimales = format.resolvedOptions().maximumFractionDigits ?? 2
  return format.format(minor / 10 ** decimales)
}

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

function Quotas({ offre }: { offre: OffrePubliee }) {
  const { t } = useTranslation()
  // `null` = illimité, pour les deux quotas. Un plafond absent n'est pas zéro.
  const illimite = t('forfaits.unlimited')
  const valeur = (quota: number | null) => (quota === null ? illimite : String(quota))

  // Les deux types d'hébergement ne décrivent pas la même chose avec les mêmes
  // champs : en dédié `max_workspaces` est la capacité de CHAQUE machine, en
  // mutualisé c'est le quota personnel du souscripteur sur le pool.
  const lignes =
    offre.hosting_type === 'dedie'
      ? [
          t('forfaits.dedicatedHosts', { value: valeur(offre.max_hosts_dedies) }),
          t('forfaits.hostCapacity', { value: valeur(offre.max_workspaces) }),
        ]
      : [t('forfaits.sharedQuota', { value: valeur(offre.max_workspaces) })]

  if (offre.duration_days !== null) {
    lignes.push(t('forfaits.duration', { value: offre.duration_days }))
  }

  return (
    <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
      {lignes.map((ligne) => (
        <li key={ligne}>{ligne}</li>
      ))}
    </ul>
  )
}

function Carte({ offre }: { offre: OffrePubliee }) {
  const { i18n } = useTranslation()
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
    </article>
  )
}

export default function ForfaitsPage() {
  const { t } = useTranslation()
  const { data: offres, isLoading, isError } = useOffresPubliques()

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between px-6 py-4">
        <Link to="/" className="text-sm text-muted-foreground hover:text-foreground">
          {t('forfaits.backHome')}
        </Link>
        <div className="flex items-center gap-3">
          <Link
            to="/auth/login"
            className="inline-flex h-9 items-center rounded-md border px-4 text-sm font-medium transition-colors hover:bg-muted"
          >
            {t('landing.ctaLogin')}
          </Link>
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
              <Carte key={offre.slug} offre={offre} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
