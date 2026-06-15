import { useTranslation } from 'react-i18next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { PluginSort } from '../api/types'

interface Props {
  value: PluginSort
  onChange: (v: PluginSort) => void
}

const SORTS: PluginSort[] = ['relevance', 'popular', 'recent', 'rating']

export function PluginSortSelect({ value, onChange }: Props) {
  const { t } = useTranslation()
  return (
    <Select value={value} onValueChange={(v) => onChange(v as PluginSort)}>
      <SelectTrigger className="w-44">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {SORTS.map((s) => (
          <SelectItem key={s} value={s}>
            {t(`profiles.plugins.sort.${s}`)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
