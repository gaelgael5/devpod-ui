import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useProviders, type PaymentProvider } from './useBillingCatalog'
import { offreVide, useOffers, useSaveOffer, type Offer } from './useBillingOffers'
import { LANGUE_PIVOT } from './offerDraft'
import OfferDescriptionTab from './OfferDescriptionTab'
import OfferPricingTab from './OfferPricingTab'

const RETOUR = '/admin/billing-offers'

/**
 * Edition d'une offre, en ecran plein.
 *
 * Deux onglets : ce que l'offre EST (nom, textes clients, droits) et comment
 * elle se VEND (canal, prix, devises). Une offre se saisit en plusieurs
 * minutes, avec un editeur markdown et autant de blocs que de langues : une
 * fenetre modale imposait un ascenseur dans un ascenseur, et masquait la liste
 * derriere elle.
 *
 * L'etat vit ici et non dans les onglets : changer d'onglet ne perd rien, et
 * l'enregistrement part d'un seul brouillon. Les actions restent hors des
 * onglets, pour qu'on puisse enregistrer sans revenir au premier.
 */
function OfferForm({ offre, canaux }: { offre: Offer; canaux: PaymentProvider[] }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const existant = Boolean(offre.slug)
  const [brouillon, setBrouillon] = useState<Offer>(offre)
  const [slugManuel, setSlugManuel] = useState(existant)
  const [manquantes, setManquantes] = useState<string[]>([])
  const [onglet, setOnglet] = useState('description')
  const enregistrer = useSaveOffer()

  function soumettre(e: React.FormEvent) {
    e.preventDefault()
    // Les champs obligatoires vivent dans l'onglet « Description ». Onglet
    // inactif = contenu demonte : le navigateur ne les valide plus, et une
    // offre sans titre partirait se faire refuser par le serveur sans que rien
    // ne designe le champ fautif. On verifie ici, et on RAMENE sur l'onglet.
    const requis = [brouillon.label, brouillon.slug, brouillon.titles[LANGUE_PIVOT] ?? '']
    if (requis.some((v) => !v.trim())) {
      setOnglet('description')
      toast.error(t('admin.offers.champsManquants'))
      return
    }
    const prices = brouillon.prices.filter((p) => p.currency !== '')
    toast.promise(enregistrer.mutateAsync({ ...brouillon, prices }), {
      loading: '…',
      success: (res) => {
        setManquantes(res.devises_manquantes)
        // Devises manquantes : pas un refus — l'offre reste vendable ailleurs —
        // mais l'absence doit se voir a la saisie, pas dans une page vide.
        if (res.devises_manquantes.length === 0) navigate(RETOUR)
        return t('admin.offers.saved', { slug: brouillon.slug })
      },
      error: (err: Error) => err.message,
    })
  }

  return (
    <form onSubmit={soumettre} className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="h-8 w-8 shrink-0"
          aria-label={t('common.back')}
          onClick={() => navigate(RETOUR)}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold">
            {existant ? brouillon.label || brouillon.slug : t('admin.offers.new')}
          </h1>
          <p className="text-sm text-muted-foreground">{t('admin.offers.help')}</p>
        </div>
      </div>

      <Tabs value={onglet} onValueChange={setOnglet}>
        <TabsList>
          <TabsTrigger value="description">{t('admin.offers.tabDescription')}</TabsTrigger>
          <TabsTrigger value="tarif">{t('admin.offers.tabPricing')}</TabsTrigger>
        </TabsList>

        <TabsContent value="description" className="mt-4">
          <OfferDescriptionTab
            brouillon={brouillon}
            setBrouillon={setBrouillon}
            existant={existant}
            slugManuel={slugManuel}
            setSlugManuel={setSlugManuel}
          />
        </TabsContent>

        <TabsContent value="tarif" className="mt-4">
          <OfferPricingTab brouillon={brouillon} setBrouillon={setBrouillon} canaux={canaux} />
        </TabsContent>
      </Tabs>

      {manquantes.length > 0 && (
        <p
          className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs"
          data-testid="devises-manquantes"
        >
          {t('admin.offers.missingCurrencies', { list: manquantes.join(', ') })}
        </p>
      )}

      <div className="flex justify-end gap-2 border-t pt-4">
        <Button type="button" variant="ghost" onClick={() => navigate(RETOUR)}>
          {t('common.cancel')}
        </Button>
        <Button type="submit">{t('common.save')}</Button>
      </div>
    </form>
  )
}

/**
 * Charge l'offre a editer, puis monte le formulaire.
 *
 * Le formulaire n'est monte qu'une fois l'offre connue : son etat est seme
 * depuis ses props, jamais recopie par un effet — sans quoi une reponse tardive
 * ecraserait une saisie en cours.
 */
export default function OfferEditor() {
  const { t } = useTranslation()
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { data: offres, isLoading } = useOffers()
  const { data: canaux = [] } = useProviders()

  if (!slug) return <OfferForm offre={offreVide()} canaux={canaux} />

  if (isLoading || offres === undefined) {
    return <p className="p-4 text-sm text-muted-foreground">{t('common.loading')}</p>
  }

  const offre = offres.find((o) => o.slug === slug)
  if (!offre) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col items-start gap-3 p-4">
        <p className="text-sm text-muted-foreground">
          {t('admin.offers.notFound', { slug })}
        </p>
        <Button type="button" variant="outline" onClick={() => navigate(RETOUR)}>
          {t('common.back')}
        </Button>
      </div>
    )
  }

  return <OfferForm offre={offre} canaux={canaux} />
}
