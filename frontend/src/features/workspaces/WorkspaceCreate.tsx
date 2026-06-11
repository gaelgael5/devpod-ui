import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Plus, X } from 'lucide-react'
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
import { useWorkspaceOps, type SourceEntry } from './useWorkspaceOps'
import { useGitCredentials } from './useGitCredentials'
import { useRecipes } from '@/features/recipes/useRecipes'
import RecipePicker from '@/features/recipes/RecipePicker'
import { useUserStore } from '@/store/user'
import { useHosts, type HostConfig } from '@/features/admin/useHosts'

/** Valeur sentinelle Radix Select pour "pas de nœud choisi" (Radix refuse les strings vides). */
const HOST_DEFAULT = '__default__'
const CRED_NONE = '__none__'

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$/

function extractErrorMessage(err: unknown): string {
  if (!(err instanceof Error)) return ''
  try {
    const parsed: unknown = JSON.parse(err.message)
    if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
      const detail = (parsed as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
    }
  } catch {
    // not JSON — use raw message
  }
  return err.message
}

function emptySource(): SourceEntry {
  return { url: '', branch: '', credential: '' }
}

// ─── Composant ligne de source ────────────────────────────────────────────────

function SourceRow({
  index,
  entry,
  onChange,
  onRemove,
  credentials,
  urlError,
}: {
  index: number
  entry: SourceEntry
  onChange: (updated: SourceEntry) => void
  onRemove?: () => void
  credentials: { name: string; host: string; kind: string }[]
  urlError?: string
}) {
  const { t } = useTranslation()
  const isPrimary = index === 0
  const urlId = `ws-source-${index}-url`
  const branchId = `ws-source-${index}-branch`

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
            className="mt-1"
          />
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

// ─── Composant principal ──────────────────────────────────────────────────────

export default function WorkspaceCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isAdmin = useUserStore((s) => s.isAdmin())
  const { createWorkspace } = useWorkspaceOps()
  const { data: recipes = [] } = useRecipes()
  const { data: hosts = [] } = useHosts()
  const { data: credentials = [] } = useGitCredentials()

  const [name, setName] = useState('')
  const [sources, setSources] = useState<SourceEntry[]>([])
  const [host, setHost] = useState('')
  const [selectedRecipes, setSelectedRecipes] = useState<string[]>([])
  const [generateSshKey, setGenerateSshKey] = useState(false)
  const [nameError, setNameError] = useState('')
  const [sourceErrors, setSourceErrors] = useState<Record<number, string>>({})
  const [serverError, setServerError] = useState('')

  function updateSource(index: number, updated: SourceEntry) {
    setSources(prev => prev.map((s, i) => (i === index ? updated : s)))
    if (sourceErrors[index]) {
      setSourceErrors(e => ({ ...e, [index]: '' }))
    }
  }

  function addSource() {
    setSources(prev => [...prev, emptySource()])
  }

  function removeSource(index: number) {
    setSources(prev => prev.filter((_, i) => i !== index))
    setSourceErrors(e => {
      const next = { ...e }
      delete next[index]
      return next
    })
  }

  function validate(): boolean {
    let valid = true
    if (!NAME_RE.test(name)) {
      setNameError(t('workspaces.form.nameHint'))
      valid = false
    } else {
      setNameError('')
    }

    const errors: Record<number, string> = {}
    sources.forEach((s, i) => {
      if (!s.url.trim()) {
        errors[i] = t('workspaces.form.sourceUrlRequired')
        valid = false
      }
    })
    setSourceErrors(errors)
    return valid
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setServerError('')
    if (!validate()) return

    try {
      await createWorkspace.mutateAsync({ name, sources, host, recipes: selectedRecipes, generateSshKey })
      navigate('/workspaces')
    } catch (err) {
      setServerError(extractErrorMessage(err) || t('errors.generic'))
    }
  }

  return (
    <div className="mx-auto max-w-lg">
      <div className="mb-6 text-sm text-muted-foreground">
        <Link to="/workspaces" className="hover:underline">{t('workspaces.title')}</Link>
        {' › '}
        {t('workspaces.new')}
      </div>

      <h1 className="mb-6 text-2xl font-semibold">{t('workspaces.new')}</h1>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div>
          <Label htmlFor="ws-name">{t('workspaces.form.name')}</Label>
          <Input
            id="ws-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-project"
          />
          {nameError && (
            <p role="alert" className="mt-1 text-sm text-destructive">
              {nameError}
            </p>
          )}
        </div>

        {isAdmin && hosts.length > 0 && (
          <div>
            <Label htmlFor="ws-host">{t('workspaces.form.node')}</Label>
            <Select
              value={host || HOST_DEFAULT}
              onValueChange={(v) => setHost(v === HOST_DEFAULT ? '' : v)}
            >
              <SelectTrigger id="ws-host">
                <SelectValue placeholder="— default —" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={HOST_DEFAULT}>— default —</SelectItem>
                {hosts.map((h: HostConfig) => (
                  <SelectItem key={h.name} value={h.name}>
                    {h.name} {h.default ? '(default)' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <div>
          <div className="flex items-center justify-between mb-2">
            <Label>{t('workspaces.form.sources')}</Label>
            <Button type="button" variant="outline" size="sm" onClick={addSource}>
              <Plus className="h-3.5 w-3.5 mr-1" />
              {t('workspaces.form.addSource')}
            </Button>
          </div>
          <div className="flex flex-col gap-2">
            {sources.map((src, i) => (
              <SourceRow
                key={i}
                index={i}
                entry={src}
                onChange={updated => updateSource(i, updated)}
                onRemove={() => removeSource(i)}
                credentials={credentials}
                urlError={sourceErrors[i]}
              />
            ))}
          </div>
          {sources.length > 0 && (
            <p className="mt-1.5 text-xs text-muted-foreground">
              {t('workspaces.form.sourcesHint')}
            </p>
          )}
        </div>

        {recipes.length > 0 && (
          <div>
            <Label>{t('workspaces.form.recipes')}</Label>
            <div className="mt-1">
              <RecipePicker
                recipes={recipes}
                selected={selectedRecipes}
                onChange={setSelectedRecipes}
              />
            </div>
          </div>
        )}

        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="ws-ssh-key"
            checked={generateSshKey}
            onChange={e => setGenerateSshKey(e.target.checked)}
            className="h-4 w-4 rounded border-input"
          />
          <Label htmlFor="ws-ssh-key" className="cursor-pointer font-normal">
            {t('workspaces.form.generateSshKey')}
          </Label>
        </div>

        {serverError && (
          <p role="alert" className="text-sm text-destructive">{serverError}</p>
        )}

        <div className="flex gap-3 pt-2">
          <Button type="submit" disabled={createWorkspace.isPending}>
            {t('workspaces.form.submit')}
          </Button>
          <Button type="button" variant="ghost" asChild>
            <Link to="/workspaces">{t('workspaces.confirm.cancel')}</Link>
          </Button>
        </div>
      </form>
    </div>
  )
}
