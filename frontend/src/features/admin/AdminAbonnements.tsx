import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { apiFetchJson } from '@/shared/api/client'
import type { EntreeHistorique } from '@/features/forfaits/useMonAbonnement'
import AdminBillingOffers from './AdminBillingOffers'

/**
 * La page admin des abonnements : une COMPOSITION, pas un nouvel écran métier.
 *
 * Quatre onglets décidés sur la fiche. Deux vivent déjà : les offres (l'écran
 * existant, embarqué tel quel — il garde sa route directe) et l'historique
 * global (la vue complète, opérations comprises, orphelines visibles). Les
 * deux autres — essais gratuits, rétention — attendent leurs fiches : l'onglet
 * existe et DIT qu'il attend, il ne simule aucun contrôle. Un onglet absent se
 * chercherait ; un faux formulaire mentirait.
 */

function HistoriqueGlobal() {
  const { t, i18n } = useTranslation()
  const { data: entrees, isLoading } = useQuery<EntreeHistorique[]>({
    queryKey: ['admin', 'billing', 'historique'],
    queryFn: () => apiFetchJson<EntreeHistorique[]>('/admin/billing/historique'),
  })

  if (isLoading) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  if (!entrees || entrees.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('admin.abonnements.historiqueVide')}</p>
  }
  const date = (iso: string) =>
    new Intl.DateTimeFormat(i18n.language, { dateStyle: 'short', timeStyle: 'short' }).format(
      new Date(iso),
    )
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm" data-testid="historique-global">
        <thead>
          <tr className="border-b bg-muted/50 text-left text-muted-foreground">
            <th className="px-4 py-2 font-medium">{t('admin.abonnements.colDate')}</th>
            <th className="px-4 py-2 font-medium">{t('admin.abonnements.colCompte')}</th>
            <th className="px-4 py-2 font-medium">{t('admin.abonnements.colEvenement')}</th>
            <th className="px-4 py-2 font-medium">{t('admin.abonnements.colOffre')}</th>
          </tr>
        </thead>
        <tbody>
          {entrees.map((e) => (
            <tr key={e.id} className="border-b last:border-0">
              <td className="px-4 py-2 text-xs text-muted-foreground">{date(e.occurred_at)}</td>
              <td className="px-4 py-2">
                {e.login ? (
                  <span className="font-medium">{e.login}</span>
                ) : (
                  // Webhook authentique jamais rattaché : l'écart doit se voir
                  // ici — c'est précisément l'endroit où on le cherchera.
                  <span className="italic text-muted-foreground">
                    {t('admin.abonnements.orphelin')}
                  </span>
                )}
              </td>
              <td className="px-4 py-2">
                {t(`abonnement.evenement.${e.kind}`)}
                {e.visibilite === 'operation' && (
                  <span className="ml-2 rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                    {t('admin.abonnements.operation')}
                  </span>
                )}
              </td>
              <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                {e.offer_slug ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminAbonnements() {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">{t('admin.abonnements.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('admin.abonnements.help')}</p>
      </div>

      <Tabs defaultValue="offres">
        <TabsList>
          <TabsTrigger value="offres">{t('admin.abonnements.tabOffres')}</TabsTrigger>
          <TabsTrigger value="essais">{t('admin.abonnements.tabEssais')}</TabsTrigger>
          <TabsTrigger value="retention">{t('admin.abonnements.tabRetention')}</TabsTrigger>
          <TabsTrigger value="historique">{t('admin.abonnements.tabHistorique')}</TabsTrigger>
        </TabsList>

        <TabsContent value="offres" className="mt-4">
          <AdminBillingOffers />
        </TabsContent>

        <TabsContent value="essais" className="mt-4">
          <p className="text-sm text-muted-foreground">{t('admin.abonnements.essaisAVenir')}</p>
        </TabsContent>

        <TabsContent value="retention" className="mt-4">
          <p className="text-sm text-muted-foreground">{t('admin.abonnements.retentionAVenir')}</p>
        </TabsContent>

        <TabsContent value="historique" className="mt-4">
          <HistoriqueGlobal />
        </TabsContent>
      </Tabs>
    </div>
  )
}
