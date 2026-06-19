import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import BashEditor from '@/features/admin/BashEditor'
import { apiFetchJson } from '@/shared/api/client'
import {
  useRecipes,
  useForkRecipe,
  useCreateUserRecipe,
  useUpdateUserRecipe,
  useDeleteUserRecipe,
  type UserRecipeCreateBody,
  type UserRecipeUpdateBody,
} from './useRecipes'
import type { Recipe } from './types'

const DEFAULT_SCRIPT = '#!/usr/bin/env bash\nset -e\necho "Installing..."\n'
const ID_RE = /^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$/

interface FormState {
  id: string
  version: string
  description: string
  type: 'install' | 'start'
  install_script: string
}

const EMPTY_FORM: FormState = {
  id: '',
  version: '1.0.0',
  description: '',
  type: 'install',
  install_script: DEFAULT_SCRIPT,
}

export default function RecipeCatalog() {
  const { t } = useTranslation()
  const { data: recipes, isLoading } = useRecipes()
  const forkMutation = useForkRecipe()
  const createMutation = useCreateUserRecipe()
  const updateMutation = useUpdateUserRecipe()
  const deleteMutation = useDeleteUserRecipe()

  const [query, setQuery] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [scriptLoading, setScriptLoading] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const sharedRecipes = useMemo(
    () => (recipes ?? []).filter((r) => r.scope === 'shared' || r.scope === 'builtin'),
    [recipes],
  )
  const userRecipes = useMemo(
    () => (recipes ?? []).filter((r) => r.scope === 'user'),
    [recipes],
  )

  const filteredShared = useMemo(() => {
    const q = query.toLowerCase()
    if (!q) return sharedRecipes
    return sharedRecipes.filter(
      (r) => r.id.toLowerCase().includes(q) || r.description.toLowerCase().includes(q),
    )
  }, [sharedRecipes, query])

  const filteredUser = useMemo(() => {
    const q = query.toLowerCase()
    if (!q) return userRecipes
    return userRecipes.filter(
      (r) => r.id.toLowerCase().includes(q) || r.description.toLowerCase().includes(q),
    )
  }, [userRecipes, query])

  function setField<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function openCreate() {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setDialogOpen(true)
  }

  async function openEdit(recipe: Recipe) {
    setEditingId(recipe.id)
    setForm({
      id: recipe.id,
      version: recipe.version,
      description: recipe.description,
      type: recipe.type,
      install_script: '',
    })
    setDialogOpen(true)
    setScriptLoading(true)
    try {
      const full = await apiFetchJson<Recipe>(`/me/recipes/${encodeURIComponent(recipe.id)}`)
      setForm((f) => ({ ...f, install_script: full.install_script ?? '' }))
    } finally {
      setScriptLoading(false)
    }
  }

  function handleClose(open: boolean) {
    if (!open) {
      setDialogOpen(false)
      setEditingId(null)
      setForm(EMPTY_FORM)
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (editingId !== null) {
      const body: UserRecipeUpdateBody = {
        id: editingId,
        version: form.version,
        description: form.description,
        install_script: form.install_script,
      }
      updateMutation.mutate(body, { onSuccess: () => handleClose(false) })
    } else {
      const body: UserRecipeCreateBody = {
        id: form.id,
        version: form.version,
        description: form.description,
        type: form.type,
        install_script: form.install_script,
      }
      createMutation.mutate(body, { onSuccess: () => handleClose(false) })
    }
  }

  const isSaving = createMutation.isPending || updateMutation.isPending
  const isEditing = editingId !== null

  if (isLoading) return <p className="text-sm text-muted-foreground">…</p>

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-center gap-4">
        <h1 className="text-2xl font-semibold">{t('recipes.title')}</h1>
        <Input
          placeholder={t('recipes.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="max-w-xs"
        />
      </div>

      {/* ── Recettes partagées ────────────────────────────────────────── */}
      {sharedRecipes.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">{t('recipes.shared')}</h2>
          {filteredShared.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('recipes.noMatch')}</p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filteredShared.map((r) => (
                <div key={r.id} className="flex flex-col gap-2 rounded-lg border bg-card p-4">
                  <div className="font-medium">{r.id}</div>
                  <div className="text-sm text-muted-foreground">{r.description}</div>
                  <div className="text-xs text-muted-foreground">v{r.version}</div>
                  <div className="mt-auto pt-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => forkMutation.mutate(r.id)}
                      disabled={forkMutation.isPending && forkMutation.variables === r.id}
                    >
                      {forkMutation.isPending && forkMutation.variables === r.id
                        ? t('recipes.forking')
                        : t('recipes.fork')}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── Mes recettes ─────────────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">{t('recipes.personal')}</h2>
          <Button size="sm" onClick={openCreate}>
            <Plus className="mr-1 h-4 w-4" />
            {t('recipes.new')}
          </Button>
        </div>
        {userRecipes.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('recipes.empty')}</p>
        ) : filteredUser.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('recipes.noMatch')}</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredUser.map((r) => (
              <div key={r.id} className="flex flex-col gap-2 rounded-lg border bg-card p-4">
                <div className="font-medium">{r.id}</div>
                <div className="text-sm text-muted-foreground">{r.description}</div>
                <div className="text-xs text-muted-foreground">v{r.version}</div>
                <div className="mt-auto flex gap-2 pt-2">
                  <Button size="sm" variant="outline" onClick={() => openEdit(r)}>
                    {t('workspaces.actions.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                    onClick={() => setConfirmDeleteId(r.id)}
                  >
                    {t('workspaces.actions.delete')}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Dialog création / édition ─────────────────────────────────── */}
      <Dialog open={dialogOpen} onOpenChange={handleClose}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>
              {isEditing ? t('recipes.editTitle') : t('recipes.createTitle')}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {isEditing ? t('recipes.editTitle') : t('recipes.createTitle')}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="r-id">{t('recipes.form.id')}</Label>
              <Input
                id="r-id"
                value={form.id}
                onChange={(e) => setField('id', e.target.value)}
                placeholder="my-tool"
                pattern={ID_RE.source}
                required
                readOnly={isEditing}
                className={isEditing ? 'cursor-not-allowed opacity-60' : ''}
              />
              {!isEditing && (
                <p className="text-xs text-muted-foreground">{t('recipes.form.idHint')}</p>
              )}
            </div>
            <div className="flex gap-4">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="r-version">{t('recipes.form.version')}</Label>
                <Input
                  id="r-version"
                  value={form.version}
                  onChange={(e) => setField('version', e.target.value)}
                  required
                />
              </div>
              {!isEditing && (
                <div className="flex flex-1 flex-col gap-1.5">
                  <Label htmlFor="r-type">{t('recipes.form.type')}</Label>
                  <select
                    id="r-type"
                    value={form.type}
                    onChange={(e) => setField('type', e.target.value as 'install' | 'start')}
                    className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm"
                  >
                    <option value="install">{t('recipes.form.typeInstall')}</option>
                    <option value="start">{t('recipes.form.typeStart')}</option>
                  </select>
                </div>
              )}
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="r-desc">{t('recipes.form.description')}</Label>
                <Input
                  id="r-desc"
                  value={form.description}
                  onChange={(e) => setField('description', e.target.value)}
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t('recipes.form.script')}</Label>
              {scriptLoading ? (
                <p className="text-sm text-muted-foreground">…</p>
              ) : (
                <BashEditor
                  value={form.install_script}
                  onChange={(v) => setField('install_script', v)}
                />
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => handleClose(false)}>
                {t('recipes.delete.cancel')}
              </Button>
              <Button type="submit" disabled={isSaving}>
                {t('recipes.form.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Dialog confirmation suppression ──────────────────────────── */}
      <Dialog
        open={confirmDeleteId !== null}
        onOpenChange={(o) => !o && setConfirmDeleteId(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('recipes.delete.confirm')}</DialogTitle>
            <DialogDescription>
              {t('recipes.delete.description', { id: confirmDeleteId })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmDeleteId(null)}>
              {t('recipes.delete.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (!confirmDeleteId) return
                deleteMutation.mutate(confirmDeleteId, {
                  onSuccess: () => setConfirmDeleteId(null),
                })
              }}
            >
              {t('recipes.delete.confirm_btn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
