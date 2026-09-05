import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { apiFetchJson } from '@/shared/api/client'

/**
 * L'adresse de facturation du compte — la valeur COURANTE.
 *
 * Deux choses que cette section dit à l'utilisateur, parce qu'elles sont
 * contre-intuitives : l'adresse est chiffrée côté portail, et la modifier ne
 * change PAS les souscriptions passées — l'adresse d'une facture émise est
 * figée, comme son prix.
 */

export interface AdresseFacturation {
  line1: string
  line2: string
  city: string
  postal_code: string
  state: string
  country: string
}

const VIDE: AdresseFacturation = {
  line1: '',
  line2: '',
  city: '',
  postal_code: '',
  state: '',
  country: '',
}

function Champ({
  id,
  label,
  value,
  onChange,
  required,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  required?: boolean
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} required={required} />
    </div>
  )
}

function Formulaire({ initial }: { initial: AdresseFacturation | null }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [adresse, setAdresse] = useState<AdresseFacturation>(initial ?? VIDE)

  const save = useMutation({
    mutationFn: () =>
      apiFetchJson<AdresseFacturation>('/me/billing-address', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...adresse, country: adresse.country.toUpperCase() }),
      }),
    onSuccess: () => {
      toast.success(t('profile.billingAddress.saved'))
      void qc.invalidateQueries({ queryKey: ['me', 'billing-address'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const maj = (champ: keyof AdresseFacturation) => (v: string) =>
    setAdresse((cur) => ({ ...cur, [champ]: v }))

  const incomplet =
    !adresse.line1.trim() ||
    !adresse.city.trim() ||
    !adresse.postal_code.trim() ||
    !/^[A-Za-z]{2}$/.test(adresse.country.trim())

  return (
    <div className="mt-4 flex flex-col gap-3">
      <Champ
        id="addr-line1"
        label={t('profile.billingAddress.line1')}
        value={adresse.line1}
        onChange={maj('line1')}
        required
      />
      <Champ
        id="addr-line2"
        label={t('profile.billingAddress.line2')}
        value={adresse.line2}
        onChange={maj('line2')}
      />
      <div className="grid grid-cols-2 gap-3">
        <Champ
          id="addr-postal"
          label={t('profile.billingAddress.postalCode')}
          value={adresse.postal_code}
          onChange={maj('postal_code')}
          required
        />
        <Champ
          id="addr-city"
          label={t('profile.billingAddress.city')}
          value={adresse.city}
          onChange={maj('city')}
          required
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Champ
          id="addr-state"
          label={t('profile.billingAddress.state')}
          value={adresse.state}
          onChange={maj('state')}
        />
        <Champ
          id="addr-country"
          label={t('profile.billingAddress.country')}
          value={adresse.country}
          onChange={maj('country')}
          required
        />
      </div>
      <div>
        <Button onClick={() => save.mutate()} disabled={save.isPending || incomplet}>
          {save.isPending ? '…' : t('common.save')}
        </Button>
      </div>
    </div>
  )
}

export default function BillingAddressSection() {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery<AdresseFacturation | null>({
    queryKey: ['me', 'billing-address'],
    queryFn: () => apiFetchJson<AdresseFacturation | null>('/me/billing-address'),
  })

  return (
    <section className="mt-10 border-t pt-6">
      <h2 className="mb-1 text-lg font-semibold">{t('profile.billingAddress.title')}</h2>
      <p className="mb-1 text-sm text-muted-foreground">{t('profile.billingAddress.intro')}</p>
      <p className="text-xs text-muted-foreground">{t('profile.billingAddress.figee')}</p>
      {isLoading ? (
        <p className="mt-3 text-sm text-muted-foreground">{t('common.loading')}</p>
      ) : (
        <Formulaire initial={data ?? null} />
      )}
    </section>
  )
}
