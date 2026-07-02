import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useGrafanaOidc, useSaveGrafanaOidc, type GrafanaOidcConfig } from './useAdminOidc'

function CopyRow({ value }: { value: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  function copy() {
    void navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="mt-1 flex items-center gap-2 rounded bg-muted px-2 py-1">
      <code className="flex-1 break-all text-xs">{value}</code>
      <button type="button" onClick={copy} title={t('admin.oidc.grafana.guide.copy')}>
        {copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}

function GrafanaOidcForm({ initial }: { initial: GrafanaOidcConfig }) {
  const { t } = useTranslation()
  const save = useSaveGrafanaOidc()
  const [clientId, setClientId] = useState(initial.client_id)
  const [secret, setSecret] = useState('')

  function handleSave() {
    save.mutate(
      { client_id: clientId, client_secret: secret || undefined },
      {
        onSuccess: () => {
          toast.success(t('admin.oidc.grafana.saved'))
          setSecret('')
        },
      },
    )
  }

  const origin = (() => {
    try { return initial.redirect_uri ? new URL(initial.redirect_uri).origin : null } catch { return null }
  })()

  return (
    <div className="mt-8 border-t pt-8">
      <h2 className="mb-1 font-semibold">{t('admin.oidc.grafana.title')}</h2>
      <p className="mb-4 text-sm text-muted-foreground">{t('admin.oidc.grafana.intro')}</p>

      {!initial.auth_url && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('admin.oidc.grafana.missingIssuer')}</span>
        </div>
      )}
      {initial.auth_url && !initial.redirect_uri && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('admin.oidc.grafana.missingGrafanaUrl')}</span>
        </div>
      )}

      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="grafana-oidc-client-id">{t('admin.oidc.grafana.clientId')}</Label>
          <Input
            id="grafana-oidc-client-id"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="agflow-grafana"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="grafana-oidc-client-secret">{t('admin.oidc.grafana.clientSecret')}</Label>
          <Input
            id="grafana-oidc-client-secret"
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            autoComplete="new-password"
            placeholder={initial.has_secret ? t('admin.oidc.grafana.secretKept') : ''}
          />
          <p className="text-xs text-muted-foreground">{t('admin.oidc.grafana.secretHint')}</p>
        </div>

        {initial.auth_url && (
          <div className="rounded-md border bg-muted/30 p-3 text-xs">
            <p className="mb-2 font-medium text-muted-foreground">
              {t('admin.oidc.grafana.endpoints')}
            </p>
            <dl className="flex flex-col gap-1">
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-muted-foreground">
                  {t('admin.oidc.grafana.authUrl')}
                </dt>
                <dd className="break-all font-mono">{initial.auth_url}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-muted-foreground">
                  {t('admin.oidc.grafana.tokenUrl')}
                </dt>
                <dd className="break-all font-mono">{initial.token_url}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-muted-foreground">
                  {t('admin.oidc.grafana.userinfoUrl')}
                </dt>
                <dd className="break-all font-mono">{initial.userinfo_url}</dd>
              </div>
            </dl>
          </div>
        )}

        <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('admin.oidc.grafana.restartNeeded')}</span>
        </div>

        <div>
          <Button onClick={handleSave} disabled={save.isPending || !clientId}>
            {save.isPending ? '…' : t('admin.oidc.grafana.save')}
          </Button>
        </div>
      </div>

      {initial.redirect_uri && (
        <div className="mt-6 rounded-lg border bg-muted/30 p-4 text-sm">
          <h3 className="mb-1 font-semibold">{t('admin.oidc.grafana.guide.title')}</h3>
          <ol className="flex list-decimal flex-col gap-2 pl-5">
            <li>{t('admin.oidc.grafana.guide.step1')}</li>
            <li>{t('admin.oidc.grafana.guide.step2')}</li>
            <li>
              {t('admin.oidc.grafana.guide.step3')}
              <CopyRow value={initial.redirect_uri} />
            </li>
            {origin && (
              <li>
                {t('admin.oidc.grafana.guide.step4')} <code className="text-xs">{origin}</code>
              </li>
            )}
            <li>{t('admin.oidc.grafana.guide.step5')}</li>
          </ol>
        </div>
      )}
    </div>
  )
}

export default function GrafanaOidcSection() {
  const { data, isLoading } = useGrafanaOidc()
  if (isLoading || !data) return null
  return <GrafanaOidcForm initial={data} />
}
