import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PluginBrowser } from './components/PluginBrowser'
import { useProfile, useSaveProfile } from './hooks/useProfiles'

function useSlugFromPath(): string | undefined {
  const { pathname } = useLocation()
  const segment = pathname.split('/').filter(Boolean).pop()
  return segment === 'new' || segment === undefined ? undefined : segment
}

export default function ProfileEditor() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const slug = useSlugFromPath()

  const { data: existing } = useProfile('user', slug)
  const save = useSaveProfile()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [settings] = useState<Record<string, unknown>>({})

  useEffect(() => {
    if (existing) {
      setName(existing.name)
      setDescription(existing.description)
      setSelected(new Set(existing.extensions))
    }
  }, [existing])

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const devcontainerPreview = useMemo(
    () =>
      JSON.stringify(
        { customizations: { vscode: { extensions: [...selected], settings } } },
        null,
        2,
      ),
    [selected, settings],
  )

  const onSave = () =>
    save.mutate(
      { slug, body: { name, description, extensions: [...selected], settings } },
      { onSuccess: () => navigate('/profiles') },
    )

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-col gap-3 max-w-xl">
        <Label htmlFor="profile-name">{t('profiles.fields.name')}</Label>
        <Input
          id="profile-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('profiles.fields.name')}
        />
        <Label htmlFor="profile-desc">{t('profiles.fields.description')}</Label>
        <Input
          id="profile-desc"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('profiles.fields.description')}
        />
      </div>

      <section>
        <h2 className="mb-2 text-lg font-medium">{t('profiles.plugins.title')}</h2>
        <PluginBrowser selectedIds={selected} onToggle={toggle} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">{t('profiles.preview')}</h2>
        <pre role="code" className="overflow-x-auto rounded-md bg-muted p-4 text-xs">
          {devcontainerPreview}
        </pre>
      </section>

      <div className="flex gap-2">
        <Button onClick={onSave} disabled={!name.trim() || save.isPending}>
          {t('common.save')}
        </Button>
        <Button variant="ghost" onClick={() => navigate('/profiles')}>
          {t('common.cancel')}
        </Button>
      </div>
    </div>
  )
}
