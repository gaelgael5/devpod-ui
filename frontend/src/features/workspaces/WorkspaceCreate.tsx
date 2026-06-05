import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useWorkspaceOps } from './useWorkspaceOps'
import { useRecipes } from '@/features/recipes/useRecipes'
import RecipePicker from '@/features/recipes/RecipePicker'
import { useUserStore } from '@/store/user'
import { useHosts } from '@/features/admin/useHosts'

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$/

function extractErrorMessage(err: unknown): string {
  if (!(err instanceof Error)) return ''
  // Try to parse JSON body (e.g. FastAPI 422 { detail: "..." })
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

export default function WorkspaceCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isAdmin = useUserStore((s) => s.isAdmin())
  const { createWorkspace } = useWorkspaceOps()
  const { data: recipes = [] } = useRecipes()
  const { data: hosts = [] } = useHosts()

  const [name, setName] = useState('')
  const [source, setSource] = useState('')
  const [host, setHost] = useState('')
  const [selectedRecipes, setSelectedRecipes] = useState<string[]>([])
  const [nameError, setNameError] = useState('')
  const [serverError, setServerError] = useState('')

  function validate(): boolean {
    if (!NAME_RE.test(name)) {
      setNameError(t('workspaces.form.nameHint'))
      return false
    }
    setNameError('')
    if (!source.trim()) {
      setServerError(t('errors.generic'))
      return false
    }
    return true
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setServerError('')
    if (!validate()) return

    try {
      await createWorkspace.mutateAsync({ name, source, host, recipes: selectedRecipes })
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

        <div>
          <Label htmlFor="ws-source">{t('workspaces.form.source')}</Label>
          <Input
            id="ws-source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="github.com/org/repo"
          />
        </div>

        {isAdmin && hosts.length > 0 && (
          <div>
            <Label htmlFor="ws-host">{t('workspaces.form.node')}</Label>
            <select
              id="ws-host"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            >
              <option value="">— default —</option>
              {hosts.map((h) => (
                <option key={h.name} value={h.name}>
                  {h.name} {h.default ? '(default)' : ''}
                </option>
              ))}
            </select>
          </div>
        )}

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

        {serverError && (
          <p className="text-sm text-destructive">{serverError}</p>
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
