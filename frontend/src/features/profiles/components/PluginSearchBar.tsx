import { Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'

interface Props {
  value: string
  onChange: (v: string) => void
}

export function PluginSearchBar({ value, onChange }: Props) {
  const { t } = useTranslation()
  return (
    <div className="relative flex-1">
      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t('profiles.plugins.searchPlaceholder')}
        aria-label={t('profiles.plugins.searchPlaceholder')}
        className="pl-8"
      />
    </div>
  )
}
