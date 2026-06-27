import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAdminOidc, useSaveOidc, type OidcConfig } from './useAdminOidc'

/** Formulaire — monté avec les valeurs chargées, state initialisé en lazy (pas d'effet). */
function OidcForm({ initial }: { initial: OidcConfig }) {
  const { t } = useTranslation()
  const save = useSaveOidc()
  const [issuer, setIssuer] = useState(initial.issuer)
  const [clientId, setClientId] = useState(initial.client_id)
  const [secret, setSecret] = useState('')

  function handleSave() {
    save.mutate(
      { issuer, client_id: clientId, client_secret: secret || undefined },
      { onSuccess: () => { toast.success(t('admin.oidc.saved')); setSecret('') } },
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{t('admin.oidc.warning')}</span>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="oidc-issuer">{t('admin.oidc.issuer')}</Label>
        <Input
          id="oidc-issuer"
          value={issuer}
          onChange={(e) => setIssuer(e.target.value)}
          placeholder="https://security.example.org/realms/yoops"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="oidc-client-id">{t('admin.oidc.clientId')}</Label>
        <Input
          id="oidc-client-id"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          placeholder="workspace-portal"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="oidc-client-secret">{t('admin.oidc.clientSecret')}</Label>
        <Input
          id="oidc-client-secret"
          type="password"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          autoComplete="new-password"
          placeholder={initial.has_secret ? t('admin.oidc.secretKept') : ''}
        />
        <p className="text-xs text-muted-foreground">{t('admin.oidc.secretHint')}</p>
      </div>

      <div>
        <Button onClick={handleSave} disabled={save.isPending || !issuer || !clientId}>
          {save.isPending ? '…' : t('admin.oidc.save')}
        </Button>
      </div>
    </div>
  )
}

/** Aide pas-à-pas pour créer le client OIDC dans Keycloak, avec le redirect_uri exact. */
function KeycloakGuide({ redirectUri }: { redirectUri: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const origin = (() => {
    try { return new URL(redirectUri).origin } catch { return redirectUri }
  })()

  function copy() {
    void navigator.clipboard.writeText(redirectUri)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="mt-8 rounded-lg border bg-muted/30 p-4 text-sm">
      <h2 className="mb-1 font-semibold">{t('admin.oidc.guide.title')}</h2>
      <p className="mb-3 text-muted-foreground">{t('admin.oidc.guide.intro')}</p>
      <ol className="flex list-decimal flex-col gap-2 pl-5">
        <li>{t('admin.oidc.guide.step1')}</li>
        <li>{t('admin.oidc.guide.step2')}</li>
        <li>
          {t('admin.oidc.guide.step3')}
          <div className="mt-1 flex items-center gap-2 rounded bg-muted px-2 py-1">
            <code className="flex-1 break-all text-xs">{redirectUri}</code>
            <button type="button" onClick={copy} title={t('admin.oidc.guide.copy')}>
              {copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
          </div>
        </li>
        <li>
          {t('admin.oidc.guide.step4')} <code className="text-xs">{origin}</code>
        </li>
        <li>{t('admin.oidc.guide.step5')}</li>
        <li>{t('admin.oidc.guide.step6')}</li>
        <li className="text-amber-700">⚠ {t('admin.oidc.guide.step7')}</li>
      </ol>
    </div>
  )
}

export default function AdminOidc() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useAdminOidc()

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="mb-6 text-2xl font-semibold">{t('admin.oidc.title')}</h1>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && (
        <>
          <OidcForm initial={data} />
          <KeycloakGuide redirectUri={data.redirect_uri} />
        </>
      )}
    </div>
  )
}
