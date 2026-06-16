import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
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
import { useProfiles } from '@/features/profiles/hooks/useProfiles'
import { useStartRecipes } from './useStartRecipes'
import OrderedRecipePicker from '@/features/recipes/OrderedRecipePicker'
import ProfileSelector from './ProfileSelector'
import SourceRow from './SourceRow'
import { useUserStore } from '@/store/user'
import { useHosts, type HostConfig } from '@/features/admin/useHosts'
import { apiFetchJson } from '@/shared/api/client'

/** Valeur sentinelle Radix Select pour "pas de nœud choisi" (Radix refuse les strings vides). */
const HOST_DEFAULT = '__default__'

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

// ─── Composant principal ──────────────────────────────────────────────────────

export default function WorkspaceCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isAdmin = useUserStore((s) => s.isAdmin())
  const { createWorkspace } = useWorkspaceOps()
  const { data: recipes = [] } = useRecipes()
  const { data: hosts = [] } = useHosts()
  const { data: credentials = [] } = useGitCredentials()
  const { data: profiles = [] } = useProfiles()
  const { data: startRecipes = [] } = useStartRecipes()

  const [name, setName] = useState('')
  const [sources, setSources] = useState<SourceEntry[]>([])
  const [host, setHost] = useState('')
  const [selectedRecipes, setSelectedRecipes] = useState<string[]>([])
  const [selectedStartRecipes, setSelectedStartRecipes] = useState<string[]>([])
  const [showNewStart, setShowNewStart] = useState(false)
  const [newStartId, setNewStartId] = useState('')
  const [newStartScript, setNewStartScript] = useState('#!/usr/bin/env bash\nset -euo pipefail\n')
  const [newStartSaving, setNewStartSaving] = useState(false)
  const [generateSshKey, setGenerateSshKey] = useState(false)
  const [profile, setProfile] = useState('')
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
      const profileRef = profile
        ? (() => {
            const [scope, slug] = profile.split(':') as ['shared' | 'user', string]
            return { scope, slug }
          })()
        : undefined
      await createWorkspace.mutateAsync({
        name,
        sources,
        host,
        recipes: selectedRecipes,
        generateSshKey,
        profile: profileRef,
        startRecipes: selectedStartRecipes,
      })
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
              <OrderedRecipePicker
                recipes={recipes}
                selected={selectedRecipes}
                onChange={setSelectedRecipes}
              />
            </div>
          </div>
        )}

        {/* ─── Start recipes ──────────────────────────────────────────────── */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <Label>{t('workspaces.form.startRecipes')}</Label>
            <Button type="button" variant="outline" size="sm" onClick={() => setShowNewStart(s => !s)}>
              {t('workspaces.form.newStartRecipe')}
            </Button>
          </div>

          {startRecipes.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {startRecipes.map((r) => {
                const selected = selectedStartRecipes.includes(r.id)
                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() =>
                      setSelectedStartRecipes(prev =>
                        selected ? prev.filter(id => id !== r.id) : [...prev, r.id]
                      )
                    }
                    className={`rounded-sm px-2 py-0.5 text-xs border transition-colors ${
                      selected
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-muted text-muted-foreground border-border hover:border-primary'
                    }`}
                  >
                    {r.id}
                  </button>
                )
              })}
            </div>
          )}

          {showNewStart && (
            <div className="mt-2 rounded-md border bg-muted/30 p-3 flex flex-col gap-2">
              <div>
                <Label htmlFor="new-start-id">{t('workspaces.form.startRecipeId')}</Label>
                <Input
                  id="new-start-id"
                  value={newStartId}
                  onChange={e => setNewStartId(e.target.value)}
                  placeholder="my-start"
                />
                <p className="text-xs text-muted-foreground mt-0.5">{t('workspaces.form.startRecipeIdHint')}</p>
              </div>
              <div>
                <Label htmlFor="new-start-script">{t('workspaces.form.startRecipeScript')}</Label>
                <textarea
                  id="new-start-script"
                  value={newStartScript}
                  onChange={e => setNewStartScript(e.target.value)}
                  rows={4}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono"
                />
              </div>
              <Button
                type="button"
                size="sm"
                disabled={newStartSaving || !newStartId.trim()}
                onClick={async () => {
                  setNewStartSaving(true)
                  try {
                    await apiFetchJson('/me/start-recipes', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ id: newStartId, script: newStartScript }),
                    })
                    toast.success(t('workspaces.form.startRecipeCreated', { id: newStartId }))
                    queryClient.invalidateQueries({ queryKey: ['recipes', 'start'] })
                    setSelectedStartRecipes(prev => [...prev, newStartId])
                    setNewStartId('')
                    setNewStartScript('#!/usr/bin/env bash\nset -euo pipefail\n')
                    setShowNewStart(false)
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : t('errors.generic'))
                  } finally {
                    setNewStartSaving(false)
                  }
                }}
              >
                {t('workspaces.form.addStartRecipe')}
              </Button>
            </div>
          )}
        </div>

        <ProfileSelector profiles={profiles} value={profile} onChange={setProfile} />

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
