import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useProfile, useUpdateProfile } from './useProfile'

export default function ProfilePage() {
  const { t } = useTranslation()
  const { data: profile, isLoading } = useProfile()
  const update = useUpdateProfile()

  const [displayName, setDisplayName] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (profile) setDisplayName(profile.display_name)
  }, [profile])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaved(false)
    await update.mutateAsync(displayName)
    setSaved(true)
  }

  if (isLoading) return <p className="text-muted-foreground">…</p>

  return (
    <div className="max-w-lg">
      <h1 className="mb-6 text-2xl font-semibold">{t('profile.title')}</h1>

      <form onSubmit={handleSubmit} className="flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="login">{t('profile.login')}</Label>
          <Input id="login" value={profile?.login ?? ''} readOnly className="opacity-60" />
          <p className="text-xs text-muted-foreground">{t('profile.loginHint')}</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="email">{t('profile.email')}</Label>
          <Input id="email" value={profile?.email ?? ''} readOnly className="opacity-60" />
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

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={update.isPending}>
            {t('profile.save')}
          </Button>
          {saved && !update.isPending && (
            <span className="text-sm text-green-600">{t('profile.saved')}</span>
          )}
          {update.isError && (
            <span className="text-sm text-destructive">{t('profile.saveError')}</span>
          )}
        </div>
      </form>
    </div>
  )
}
