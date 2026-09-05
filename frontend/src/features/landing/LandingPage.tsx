import { Link, Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useOptionalSession } from '@/features/auth/useOptionalSession'
import LanguageSelect from '@/shared/nav/LanguageSelect'

/**
 * Page d'accueil publique : ce que fait l'application, et par où entrer.
 *
 * Elle ne liste PAS les forfaits — la tarification a sa propre page, atteinte
 * par « Essayez gratuitement ».
 *
 * Le texte est rédigé à partir de la description du produit portée par le dépôt
 * (`README.md`, `specs/01_ARCHITECTURE.md`) plutôt que d'un discours inventé :
 * il n'affirme que ce que l'application fait réellement. Il reste à valider par
 * l'architecte, à qui appartient le positionnement.
 *
 * Contrainte tenue : **aucun appel authentifié**. `useOptionalSession` lit `/me`
 * sans passer par la redirection globale sur 401, et le sélecteur de langue est
 * en mode non persistant — un visiteur anonyme n'a pas de compte où ranger son
 * choix.
 */

/** Une étape ou un argument : même forme, deux sections. */
function Bloc({ titre, corps }: { titre: string; corps: string }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-medium">{titre}</h3>
      <p className="text-sm text-muted-foreground">{corps}</p>
    </div>
  )
}

export default function LandingPage() {
  const { t } = useTranslation()
  const { data: session } = useOptionalSession()

  // Un abonné n'a rien à faire sur une page de présentation.
  //
  // Tant que la session n'est pas résolue, `data` vaut `undefined` et la landing
  // s'affiche : on privilégie le visiteur anonyme, qui est la raison d'être de
  // cette page. Un utilisateur connecté verra donc brièvement la landing avant
  // d'être redirigé — il n'arrive ici qu'en tapant l'URL.
  if (session) return <Navigate to="/workspaces" replace />

  const etapes = [1, 2, 3] as const
  const arguments_ = [1, 2, 3] as const

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-end px-6 py-4">
        <LanguageSelect persist={false} />
      </header>

      <main className="mx-auto flex max-w-4xl flex-col gap-20 px-6 pb-24 pt-12">
        <section className="flex flex-col items-center gap-8 text-center">
          <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
            {t('landing.title')}
          </h1>
          <p className="max-w-2xl text-lg text-muted-foreground">{t('landing.subtitle')}</p>

          <div className="flex flex-col gap-3 sm:flex-row">
            <Link
              to="/forfaits"
              className="inline-flex h-11 items-center justify-center rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
              {t('landing.ctaTry')}
            </Link>
            <Link
              to="/auth/login"
              className="inline-flex h-11 items-center justify-center rounded-md border px-6 text-sm font-medium transition-colors hover:bg-muted"
            >
              {t('landing.ctaLogin')}
            </Link>
          </div>
        </section>

        <section className="flex flex-col gap-8">
          <h2 className="text-2xl font-semibold tracking-tight">{t('landing.howTitle')}</h2>
          <ol className="grid gap-8 sm:grid-cols-3">
            {etapes.map((n) => (
              <li key={n}>
                <Bloc titre={t(`landing.step${n}Title`)} corps={t(`landing.step${n}Body`)} />
              </li>
            ))}
          </ol>
        </section>

        <section className="flex flex-col gap-8">
          <h2 className="text-2xl font-semibold tracking-tight">{t('landing.whyTitle')}</h2>
          <div className="grid gap-8 sm:grid-cols-3">
            {arguments_.map((n) => (
              <Bloc
                key={n}
                titre={t(`landing.why${n}Title`)}
                corps={t(`landing.why${n}Body`)}
              />
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}
