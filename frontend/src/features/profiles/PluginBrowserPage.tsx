import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PluginBrowser } from './components/PluginBrowser'

export default function PluginBrowserPage() {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold">{t('profiles.plugins.title')}</h1>
      {selected.size > 0 && (
        <p className="text-sm text-muted-foreground">
          {t('profiles.plugins.selectedCount', { count: selected.size })} :{' '}
          {[...selected].join(', ')}
        </p>
      )}
      <PluginBrowser selectedIds={selected} onToggle={toggle} />
    </div>
  )
}
