import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { apiFetchJson } from '@/shared/api/client'
import { useSystemSecrets } from './useBillingCatalog'

/**
 * Connexion à l'instance Listmonk — le point de départ des emails du cycle
 * d'abonnement.
 *
 * La clef d'API se CHOISIT dans la liste des secrets système : jamais de slug
 * tapé à la main — une faute de frappe se découvrirait au premier envoi, sous
 * la forme d'un « secret introuvable » sans rapport apparent. Et « Tester la
 * connexion » exerce un appel authentifié : un simple GET / répondrait 200
 * même avec une clef fausse.
 */

interface ListmonkConfig {
  enabled: boolean
  url: string
  apikey_secret: string
}

interface ResultatTest {
  ok: boolean
  status_code: number | null
  motif: string
}

function Formulaire({ initial }: { initial: ListmonkConfig }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: secrets = [] } = useSystemSecrets()
  const [enabled, setEnabled] = useState(initial.enabled)
  const [url, setUrl] = useState(initial.url)
  const [secret, setSecret] = useState(initial.apikey_secret)

  const save = useMutation({
    mutationFn: () =>
      apiFetchJson<ListmonkConfig>('/admin/listmonk', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, url, apikey_secret: secret }),
      }),
    onSuccess: () => {
      toast.success(t('admin.listmonk.saved'))
      void qc.invalidateQueries({ queryKey: ['admin', 'listmonk'] })
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const test = useMutation({
    mutationFn: () =>
      apiFetchJson<ResultatTest>('/admin/listmonk/test-connection', { method: 'POST' }),
    onSuccess: (r) => {
      if (r.ok) {
        toast.success(t('admin.listmonk.testOk'))
      } else {
        const detail = r.motif || r.status_code || ''
        toast.error(t('admin.listmonk.testFail', { detail }))
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const incomplet = enabled && (!url.trim() || !secret)

  return (
    <div className="flex flex-col gap-4">
      <label htmlFor="lm-enabled" className="flex cursor-pointer items-center gap-3">
        <input
          id="lm-enabled"
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <span className="text-sm font-medium">{t('admin.listmonk.enabled')}</span>
      </label>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="lm-url">{t('admin.listmonk.url')}</Label>
        <Input
          id="lm-url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://listmonk.yoops.org"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="lm-secret">{t('admin.listmonk.secret')}</Label>
        <select
          id="lm-secret"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
        >
          <option value="">{t('admin.listmonk.choisirSecret')}</option>
          {secrets.map((s) => (
            <option key={s.slug} value={s.slug}>
              {s.label || s.slug}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">{t('admin.listmonk.secretHint')}</p>
      </div>

      {incomplet && <p className="text-sm text-destructive">{t('admin.listmonk.missing')}</p>}

      <div className="flex gap-2">
        <Button onClick={() => save.mutate()} disabled={save.isPending || incomplet}>
          {save.isPending ? '…' : t('common.save')}
        </Button>
        <Button
          variant="outline"
          onClick={() => test.mutate()}
          disabled={test.isPending || !initial.url || !initial.apikey_secret}
        >
          {test.isPending ? '…' : t('admin.listmonk.test')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t('admin.listmonk.testHint')}</p>
    </div>
  )
}

export default function AdminListmonk() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useQuery<ListmonkConfig>({
    queryKey: ['admin', 'listmonk'],
    queryFn: () => apiFetchJson<ListmonkConfig>('/admin/listmonk'),
  })

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="mb-2 text-2xl font-semibold">{t('admin.listmonk.title')}</h1>
      <p className="mb-6 text-sm text-muted-foreground">{t('admin.listmonk.intro')}</p>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && <Formulaire initial={data} />}
    </div>
  )
}
