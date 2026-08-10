import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useProfile, useTokenClaims, useUpdateProfile } from './useProfile'
import type { UserProfile } from './useProfile'

/** Attend le profil puis monte le formulaire : l'état est initialisé au montage
 (pas d'hydratation par effet — la saisie est la source de vérité, un refetch en
 arrière-plan ne l'écrase pas). */
export default function ProfilePage() {
  const { data: profile, isLoading } = useProfile()
  if (isLoading || !profile) return <p className="text-muted-foreground">…</p>
  return (
    <div className="max-w-lg">
      <ProfileForm profile={profile} />
      <TokenClaimsBlock />
    </div>
  )
}

/** Ordre d'affichage des claims (sub en tête = ancre d'identité / clé de matching). */
const CLAIM_ORDER = ['sub', 'preferred_username', 'email', 'name', 'iss', 'aud', 'exp', 'iat']

function CopyButton({ value }: { value: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => {
        navigator.clipboard.writeText(value).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1200)
        })
      }}
    >
      {copied ? t('profile.token.copied') : t('profile.token.copy')}
    </Button>
  )
}

/** Bloc « Jeton d'identité (OIDC) » : claims essentiels + boutons copier. Le jeton
 *  brut n'est jamais exposé (seuls les claims curés persistés au login). */
function TokenClaimsBlock() {
  const { t } = useTranslation()
  const { data, isLoading } = useTokenClaims()
  const claims = data?.claims ?? {}
  const keys = [
    ...CLAIM_ORDER.filter((k) => k in claims),
    ...Object.keys(claims).filter((k) => !CLAIM_ORDER.includes(k)),
  ]

  return (
    <section className="mt-10 border-t pt-6">
      <h2 className="mb-1 text-lg font-semibold">{t('profile.token.title')}</h2>
      <p className="mb-4 text-sm text-muted-foreground">{t('profile.token.intro')}</p>

      {isLoading && <p className="text-sm text-muted-foreground">…</p>}
      {!isLoading && keys.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('profile.token.empty')}</p>
      )}

      <div className="flex flex-col gap-2">
        {keys.map((key) => (
          <div
            key={key}
            className={`flex items-center gap-2 rounded-md border p-2 ${
              key === 'sub' ? 'bg-muted/50' : ''
            }`}
          >
            <span className="w-40 shrink-0 font-mono text-xs text-muted-foreground">{key}</span>
            <code className="flex-1 truncate font-mono text-sm" title={claims[key]}>
              {claims[key]}
            </code>
            <CopyButton value={claims[key]} />
          </div>
        ))}
      </div>

      <p className="mt-3 text-xs text-muted-foreground">{t('profile.token.subHint')}</p>
    </section>
  )
}

function ProfileForm({ profile }: { profile: UserProfile }) {
  const { t } = useTranslation()
  const update = useUpdateProfile()

  const [displayName, setDisplayName] = useState(profile.display_name)
  const [email, setEmail] = useState(profile.email)
  const [identity, setIdentity] = useState(profile.identity)
  const [saved, setSaved] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaved(false)
    await update.mutateAsync({ display_name: displayName, email, identity })
    setSaved(true)
  }

  return (
    <div className="max-w-lg">
      <h1 className="mb-6 text-2xl font-semibold">{t('profile.title')}</h1>

      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="login">{t('profile.login')}</Label>
          <Input id="login" value={profile.login} readOnly className="opacity-60" />
          <p className="text-xs text-muted-foreground">{t('profile.loginHint')}</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="email">{t('profile.email')}</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => { setEmail(e.target.value); setSaved(false) }}
            placeholder={t('profile.emailPlaceholder')}
            maxLength={254}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="display-name">{t('profile.displayName')}</Label>
          <Input
            id="display-name"
            value={displayName}
            onChange={(e) => { setDisplayName(e.target.value); setSaved(false) }}
            placeholder={t('profile.displayNamePlaceholder')}
            maxLength={80}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="identity">{t('profile.identity')}</Label>
          <div className="flex gap-2">
            <Input
              id="identity"
              value={identity}
              onChange={(e) => { setIdentity(e.target.value); setSaved(false) }}
              placeholder={t('profile.identityPlaceholder')}
              maxLength={200}
              className="font-mono text-sm"
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => { setIdentity(crypto.randomUUID()); setSaved(false) }}
            >
              {t('profile.identityGenerate')}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t('profile.identityHint')}</p>
        </div>

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={update.isPending}>
            {t('profile.save')}
          </Button>
          {saved && !update.isPending && (
            <span className="text-sm text-green-600">{t('profile.saved')}</span>
          )}
          {update.isError && (
            <span className="text-sm text-destructive">
              {update.error instanceof Error ? update.error.message : t('profile.saveError')}
            </span>
          )}
        </div>
      </form>
    </div>
  )
}
