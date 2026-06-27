import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { PluginBrowser } from './components/PluginBrowser'
import JsonEditor from './components/JsonEditor'
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
  const [settingsJson, setSettingsJson] = useState('{}')
  const [settingsError, setSettingsError] = useState(false)

  useEffect(() => {
    if (!existing) return
    setName(existing.name)
    setDescription(existing.description)
    setSelected(new Set(existing.extensions))
    setSettingsJson(JSON.stringify(existing.settings ?? {}, null, 2))
  }, [existing])

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const devcontainerPreview = useMemo(() => {
    let settings: Record<string, unknown> = {}
    try { settings = JSON.parse(settingsJson || '{}') } catch { /* aperçu dégradé */ }
    return JSON.stringify(
      { customizations: { vscode: { extensions: [...selected], settings } } },
      null,
      2,
    )
  }, [selected, settingsJson])

  function onSave() {
    let settings: Record<string, unknown> = {}
    try {
      settings = JSON.parse(settingsJson || '{}')
      setSettingsError(false)
    } catch {
      setSettingsError(true)
      return
    }
    save.mutate(
      { slug, body: { name, description, extensions: [...selected], settings } },
      { onSuccess: () => navigate('/profiles') },
    )
  }

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

      <Tabs defaultValue="extensions">
        <TabsList>
          <TabsTrigger value="extensions">{t('profiles.tabs.extensions')}</TabsTrigger>
          <TabsTrigger value="settings">{t('profiles.tabs.settings')}</TabsTrigger>
        </TabsList>
        <TabsContent value="extensions">
          <PluginBrowser selectedIds={selected} onToggle={toggle} />
        </TabsContent>
        <TabsContent value="settings">
          <JsonEditor
            value={settingsJson}
            onChange={(v) => { setSettingsJson(v); setSettingsError(false) }}
          />
          {settingsError && (
            <p className="mt-1 text-xs text-destructive">{t('admin.settingsInvalid')}</p>
          )}
        </TabsContent>
      </Tabs>

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
