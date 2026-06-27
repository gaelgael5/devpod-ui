import { useTranslation } from 'react-i18next'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { ProfileSummary } from '@/features/profiles/api/profiles'

/** Valeur sentinelle Radix Select pour "aucun profil" (Radix refuse les strings vides). */
const PROFILE_NONE = '__none__'

interface ProfileSelectorProps {
  profiles: ProfileSummary[]
  value: string
  onChange: (v: string) => void
}

export default function ProfileSelector({ profiles, value, onChange }: ProfileSelectorProps) {
  const { t } = useTranslation()

  if (profiles.length === 0) return null

  return (
    <div>
      <Label className="text-xs">{t('workspaces.form.profile')}</Label>
      <Select
        value={value || PROFILE_NONE}
        onValueChange={(v) => onChange(v === PROFILE_NONE ? '' : v)}
      >
        <SelectTrigger className="mt-1">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={PROFILE_NONE}>
            {t('workspaces.form.profileNone')}
          </SelectItem>
          {profiles.map((p) => (
            <SelectItem
              key={`${p.scope}:${p.slug}`}
              value={`${p.scope}:${p.slug}`}
            >
              {p.name}
              {p.scope === 'shared' ? ` ${t('workspaces.form.profileShared')}` : ''}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
