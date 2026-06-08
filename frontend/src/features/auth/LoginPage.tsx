import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { apiFetchJson } from '@/shared/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface AuthConfig {
  oidc_enabled: boolean
  local_auth_enabled: boolean
}

export default function LoginPage() {
  const { t } = useTranslation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const { data: config } = useQuery<AuthConfig>({
    queryKey: ['auth-config'],
    queryFn: () => apiFetchJson<AuthConfig>('/auth/config'),
  })

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/auth/local-login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (res.ok) {
        window.location.href = '/'
      } else {
        setError(t('auth.invalidCredentials'))
      }
    } catch {
      setError(t('auth.networkError'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm flex flex-col gap-6 px-4">
        <h1 className="text-2xl font-semibold text-center text-foreground">DevPod Portal</h1>

        {config?.local_auth_enabled && (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="username">{t('auth.username')}</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">{t('auth.password')}</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? t('auth.loggingIn') : t('auth.loginLocal')}
            </Button>
          </form>
        )}

        {config?.oidc_enabled && (
          <>
            {config.local_auth_enabled && (
              <div className="flex items-center gap-3">
                <div className="flex-1 h-px bg-border" />
                <span className="text-xs text-muted-foreground">{t('auth.or')}</span>
                <div className="flex-1 h-px bg-border" />
              </div>
            )}
            <Button variant="outline" asChild>
              <a href="/auth/oidc">{t('auth.loginOidc')}</a>
            </Button>
          </>
        )}

        {!config && (
          <p className="text-center text-sm text-muted-foreground">{t('auth.loggingIn')}</p>
        )}
      </div>
    </div>
  )
}
