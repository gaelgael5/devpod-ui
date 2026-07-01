import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useBackends, useProfiles, useProfileDetail } from '@/features/mcp/api'
import { apiFetchJson } from '@/shared/api/client'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/** Écran de consentement OAuth : l'utilisateur sélectionne un profil MCP. */
export default function ConsentPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const { data: backends = [] } = useBackends()
  const { data: profiles = [] } = useProfiles()

  const [profileId, setProfileId] = useState<string>('')
  useEffect(() => {
    if (profiles.length === 1 && !profileId) setProfileId(profiles[0].id)
  }, [profiles, profileId])

  const { data: profileDetail } = useProfileDetail(profileId || null)

  // Services inclus dans le profil sélectionné — affichage informatif uniquement.
  const grantedBackends = profileId && profileDetail
    ? backends.filter((b) => profileDetail.entries.some((e) => e.backend_id === b.id))
    : []

  const [busy, setBusy] = useState(false)

  const oauthParams = {
    client_id: params.get('client_id') ?? '',
    redirect_uri: params.get('redirect_uri') ?? '',
    code_challenge: params.get('code_challenge') ?? '',
    state: params.get('state') ?? '',
    scope: params.get('scope') ?? '',
  }

  async function decide(approve: boolean) {
    setBusy(true)
    try {
      const res = await apiFetchJson<{ redirect: string }>('/oauth/authorize/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...oauthParams, approve, profile_id: profileId || null }),
      })
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

        {/* Sélecteur de profil */}
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase text-muted-foreground">
            {t('oauth.consent.profile')}
          </span>
          {profiles.length > 0 ? (
            <Select value={profileId} onValueChange={setProfileId}>
              <SelectTrigger>
                <SelectValue placeholder={t('oauth.consent.profileNone')} />
              </SelectTrigger>
              <SelectContent>
                {profiles.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="text-sm text-muted-foreground">{t('oauth.consent.noProfiles')}</p>
          )}
        </div>

        {/* Services inclus dans le profil — lecture seule */}
        {profileId && (
          <div className="flex flex-col gap-2 rounded-md border p-3">
            <span className="text-xs font-semibold uppercase text-muted-foreground">
              {t('oauth.consent.backends')}
            </span>
            {grantedBackends.length > 0 ? (
              grantedBackends.map((b) => (
                <div key={b.id} className="flex items-center gap-2 text-sm">
                  <span className="h-2 w-2 rounded-full bg-primary/60 shrink-0" />
                  <span>{b.name}</span>
                  <code className="text-xs text-muted-foreground">{b.namespace}</code>
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">{t('oauth.consent.noBackends')}</p>
            )}
          </div>
        )}

        <div className="flex gap-3">
          <Button variant="outline" className="flex-1" disabled={busy} onClick={() => decide(false)}>
            {t('oauth.consent.deny')}
          </Button>
          <Button
            className="flex-1"
            disabled={busy || !profileId}
            onClick={() => decide(true)}
          >
            {t('oauth.consent.allow')}
          </Button>
        </div>
      </div>
    </div>
  )
}
