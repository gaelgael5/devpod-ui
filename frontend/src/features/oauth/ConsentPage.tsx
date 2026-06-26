import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useBackends } from '@/features/mcp/api'
import { apiFetchJson } from '@/shared/api/client'
import { Button } from '@/components/ui/button'

/** Écran de consentement OAuth : l'utilisateur choisit les backends MCP accordés au client. */
export default function ConsentPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const { data: backends = [] } = useBackends()
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const oauthParams = {
    client_id: params.get('client_id') ?? '',
    redirect_uri: params.get('redirect_uri') ?? '',
    code_challenge: params.get('code_challenge') ?? '',
    state: params.get('state') ?? '',
    scope: params.get('scope') ?? '',
  }

  function toggle(id: string) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function decide(approve: boolean) {
    setBusy(true)
    const grants = approve
      ? [...checked].map((id) => ({
          backend_id: id,
          backend_key_id: null,
          expose_mode: 'all',
          expose: [] as string[],
          enabled: true,
        }))
      : []
    try {
      const res = await apiFetchJson<{ redirect: string }>('/oauth/authorize/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...oauthParams, approve, grants }),
      })
      // Garde-fou anti-XSS : ne suit que http(s), jamais javascript:/data:.
      if (!/^https?:\/\//i.test(res.redirect)) throw new Error('redirection invalide')
      window.location.href = res.redirect
    } catch (e) {
      setBusy(false)
      toast.error(e instanceof Error ? e.message : t('errors.generic'))
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex w-full max-w-md flex-col gap-5 px-4">
        <h1 className="text-center text-xl font-semibold text-foreground">
          {t('oauth.consent.title')}
        </h1>
        <p className="text-center text-sm text-muted-foreground">{t('oauth.consent.intro')}</p>

        <div className="flex flex-col gap-2 rounded-md border p-3">
          <span className="text-xs font-semibold uppercase text-muted-foreground">
            {t('oauth.consent.backends')}
          </span>
          {backends.map((b) => (
            <label key={b.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={checked.has(b.id)}
                onChange={() => toggle(b.id)}
              />
              <span>{b.name}</span>
              <code className="text-xs text-muted-foreground">{b.namespace}</code>
            </label>
          ))}
          {backends.length === 0 && (
            <p className="text-xs text-muted-foreground">{t('oauth.consent.noBackends')}</p>
          )}
        </div>

        <div className="flex gap-3">
          <Button variant="outline" className="flex-1" disabled={busy} onClick={() => decide(false)}>
            {t('oauth.consent.deny')}
          </Button>
          <Button
            className="flex-1"
            disabled={busy || checked.size === 0}
            onClick={() => decide(true)}
          >
            {t('oauth.consent.allow')}
          </Button>
        </div>
      </div>
    </div>
  )
}
