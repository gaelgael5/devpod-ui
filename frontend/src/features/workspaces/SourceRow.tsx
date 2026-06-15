import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { SourceEntry } from './useWorkspaceOps'
import { useGitBranches } from './useGitBranches'

/** Valeur sentinelle Radix Select pour "pas de credential" (Radix refuse les strings vides). */
const CRED_NONE = '__none__'

interface SourceRowProps {
  index: number
  entry: SourceEntry
  onChange: (updated: SourceEntry) => void
  onRemove?: () => void
  credentials: { name: string; host: string; kind: string }[]
  urlError?: string
}

export default function SourceRow({
  index,
  entry,
  onChange,
  onRemove,
  credentials,
  urlError,
}: SourceRowProps) {
  const { t } = useTranslation()
  const isPrimary = index === 0
  const urlId = `ws-source-${index}-url`
  const branchId = `ws-source-${index}-branch`
  const branchListId = `ws-source-${index}-branches`

  const { data: gitBranches } = useGitBranches(entry.url, entry.credential)

  // Auto-remplir la branche par défaut dès que le repo est résolu
  useEffect(() => {
    if (gitBranches?.default && !entry.branch) {
      onChange({ ...entry, branch: gitBranches.default })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gitBranches?.default])

  return (
    <div className="rounded-md border p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">
          {isPrimary
            ? t('workspaces.form.primarySource')
            : t('workspaces.form.additionalSource', { n: index })}
        </span>
        {onRemove && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={onRemove}
            aria-label={t('workspaces.form.removeSource')}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      <div>
        <Label htmlFor={urlId} className="text-xs">URL</Label>
        <Input
          id={urlId}
          value={entry.url}
          onChange={e => onChange({ ...entry, url: e.target.value })}
          placeholder="github.com/org/repo"
          className="mt-1"
        />
        {urlError && (
          <p role="alert" className="mt-1 text-xs text-destructive">{urlError}</p>
        )}
      </div>

      <div className={credentials.length > 0 ? 'grid grid-cols-2 gap-2' : ''}>
        <div>
          <Label htmlFor={branchId} className="text-xs">{t('workspaces.form.branch')}</Label>
          <Input
            id={branchId}
            value={entry.branch}
            onChange={e => onChange({ ...entry, branch: e.target.value })}
            placeholder={t('workspaces.form.branchPlaceholder')}
            list={branchListId}
            className="mt-1"
          />
          <datalist id={branchListId}>
            {gitBranches?.branches.map(b => (
              <option key={b} value={b} />
            ))}
          </datalist>
        </div>

        {credentials.length > 0 && (
          <div>
            <Label className="text-xs">{t('workspaces.form.credential')}</Label>
            <Select
              value={entry.credential || CRED_NONE}
              onValueChange={v => onChange({ ...entry, credential: v === CRED_NONE ? '' : v })}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={CRED_NONE}>{t('workspaces.form.credentialNone')}</SelectItem>
                {credentials.map(c => (
                  <SelectItem key={c.name} value={c.name}>
                    {c.name} ({c.host})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    </div>
  )
}
