import { useState, useEffect, useRef } from 'react'
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

function extractHost(url: string): string {
  const trimmed = url.trim()
  if (trimmed.startsWith('git@')) {
    return trimmed.slice(4).split(':')[0].split('/')[0].toLowerCase()
  }
  try {
    return new URL(trimmed.startsWith('http') ? trimmed : `https://${trimmed}`).hostname.toLowerCase()
  } catch {
    return ''
  }
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

  // Committed = ce qui déclenche réellement la requête de branches
  const [committed, setCommitted] = useState({ url: '', credential: '' })

  const { data: gitBranches, error: branchError } = useGitBranches(committed.url, committed.credential)

  const urlHost = extractHost(entry.url)
  const filteredCredentials = credentials.filter(c => {
    if (urlHost && c.host !== urlHost) return false
    return true
  })

  // Ref pour éviter le stale closure sur entry dans les effets
  const entryRef = useRef(entry)
  entryRef.current = entry

  // Auto-remplir la branche par défaut quand committed change ou quand les données arrivent.
  // On dépend de committed.credential pour re-déclencher même si default reste 'main'.
  useEffect(() => {
    const e = entryRef.current
    if (gitBranches?.default && !e.branch) {
      onChange({ ...e, branch: gitBranches.default })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committed.url, committed.credential, gitBranches?.default])

  // Quand le credential change (après que committed.url est défini), relancer la requête
  useEffect(() => {
    if (!committed.url) return
    if (entry.credential !== committed.credential) {
      setCommitted(prev => ({ ...prev, credential: entry.credential }))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.credential])

  function handleBranchFocus() {
    const url = entry.url.trim().replace(/\.git$/, '')
    if (url.length <= 5) return
    setCommitted({ url, credential: entry.credential })
  }

  function handleUrlBlur() {
    const url = entry.url.trim().replace(/\.git$/, '')
    if (url.length <= 5) return
    const host = extractHost(url)
    const filtered = credentials.filter(c => host ? c.host === host : true)
    let credential = entry.credential
    if (!credential && filtered.length >= 1) {
      credential = filtered[0].name
      onChange({ ...entry, credential })
    }
    setCommitted({ url, credential })
  }

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
          onBlur={handleUrlBlur}
          placeholder="github.com/org/repo"
          className="mt-1"
        />
        {urlError && (
          <p role="alert" className="mt-1 text-xs text-destructive">{urlError}</p>
        )}
      </div>

      {credentials.length > 0 && (
        <div>
          <Label className="text-xs">{t('workspaces.form.credential')}</Label>
          <Select
            value={entry.credential || CRED_NONE}
            onValueChange={v => onChange({ ...entry, credential: v === CRED_NONE ? '' : v, branch: '' })}
          >
            <SelectTrigger className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={CRED_NONE}>{t('workspaces.form.credentialNone')}</SelectItem>
              {filteredCredentials.map(c => (
                <SelectItem key={c.name} value={c.name}>
                  {c.name} ({c.host})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      <div>
        <Label htmlFor={branchId} className="text-xs">{t('workspaces.form.branch')}</Label>
        <Input
          id={branchId}
          value={entry.branch}
          onChange={e => onChange({ ...entry, branch: e.target.value })}
          onFocus={handleBranchFocus}
          placeholder={t('workspaces.form.branchPlaceholder')}
          list={branchListId}
          className="mt-1"
        />
        {branchError && (
          <p role="alert" className="mt-1 text-xs text-destructive">
            {(branchError as Error).message}
          </p>
        )}
        <datalist id={branchListId}>
          {gitBranches?.branches.map((b: string) => (
            <option key={b} value={b} />
          ))}
        </datalist>
      </div>
    </div>
  )
}
