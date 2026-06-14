import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, RefreshCw } from 'lucide-react'
import Editor from 'react-simple-code-editor'
import Prism from 'prismjs'
import 'prismjs/components/prism-bash'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import type { Recipe } from '@/features/recipes/types'
import { useAdminRecipes, type RecipeCreateRequest } from './useAdminRecipes'
import { useRecipeSources, type RemoteRecipe } from './useRecipeSources'

const DEFAULT_SCRIPT = '#!/usr/bin/env bash\nset -e\necho "Installing..."\n'

interface FormState {
  id: string
  version: string
  description: string
  install_script: string
}

const EMPTY: FormState = {
  id: '',
  version: '1.0.0',
  description: '',
  install_script: DEFAULT_SCRIPT,
}

function recipeToForm(r: Recipe): FormState {
  return {
    id: r.id,
    version: r.version,
    description: r.description,
    install_script: r.install_script ?? DEFAULT_SCRIPT,
  }
}

export default function AdminRecipes() {
  const { t } = useTranslation()
  const { recipesQuery, deleteRecipe, addRecipe, updateRecipe } = useAdminRecipes()
  const { sourcesQuery, updateSources, previewQuery, importRecipe } = useRecipeSources()
  const { data: recipes, isLoading, isError } = recipesQuery
  const { data: sourcesData } = sourcesQuery
  const {
    data: previewData,
    isFetching: isLoadingGallery,
    refetch: refetchGallery,
  } = previewQuery

  const [editingId, setEditingId] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [newSourceUrl, setNewSourceUrl] = useState('')

  const sources = sourcesData?.sources ?? []
  const galleryRecipes = previewData?.recipes ?? []
  const isEditing = editingId !== null
  const isPending = addRecipe.isPending || updateRecipe.isPending

  function openEdit(recipe: Recipe) {
    setEditingId(recipe.id)
    setForm(recipeToForm(recipe))
    setOpen(true)
  }

  function handleClose(o: boolean) {
    if (!o) {
      setOpen(false)
      setEditingId(null)
      setForm(EMPTY)
    } else {
      setOpen(true)
    }
  }

  function set<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (isEditing) {
      updateRecipe.mutate(form, { onSuccess: () => handleClose(false) })
    } else {
      addRecipe.mutate(form as RecipeCreateRequest, { onSuccess: () => handleClose(false) })
    }
  }

  function addSource() {
    const url = newSourceUrl.trim()
    if (!url) return
    updateSources.mutate([...sources, url])
    setNewSourceUrl('')
  }

  function removeSource(idx: number) {
    updateSources.mutate(sources.filter((_, i) => i !== idx))
  }

  return (
    <div className="flex flex-col gap-10">

      {/* ── Sources ─────────────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t('admin.recipeSource')}</h2>
        <div className="flex flex-col gap-2">
          {sources.map((url, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <Input
                value={url}
                readOnly
                className="flex-1 font-mono text-xs opacity-80"
              />
              <Button
                size="icon"
                variant="ghost"
                onClick={() => removeSource(idx)}
                aria-label={t('admin.deleteSource')}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Input
              value={newSourceUrl}
              onChange={(e) => setNewSourceUrl(e.target.value)}
              placeholder="https://raw.githubusercontent.com/…/toc.txt"
              className="flex-1 font-mono text-xs"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addSource()
                }
              }}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={addSource}
              disabled={!newSourceUrl.trim() || updateSources.isPending}
            >
              <Plus className="h-4 w-4 mr-1" />
              {t('admin.addSource')}
            </Button>
          </div>
        </div>
      </section>

      {/* ── Galerie ─────────────────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t('admin.gallery')}</h2>
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetchGallery()}
            disabled={isLoadingGallery}
          >
            <RefreshCw
              className={`h-4 w-4 mr-1 ${isLoadingGallery ? 'animate-spin' : ''}`}
            />
            {t('admin.refreshGallery')}
          </Button>
        </div>
        {isLoadingGallery && (
          <p className="text-sm text-muted-foreground">…</p>
        )}
        {!isLoadingGallery && galleryRecipes.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('admin.recipesEmpty')}</p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {galleryRecipes.map((r: RemoteRecipe) => (
            <div key={r.source_url} className="rounded-lg border bg-card p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{r.name}</div>
                  <div className="text-xs text-muted-foreground font-mono">{r.id}</div>
                </div>
                <Button
                  size="sm"
                  onClick={() => importRecipe.mutate(r.source_url)}
                  disabled={importRecipe.isPending}
                >
                  {importRecipe.isPending
                    ? t('admin.importing')
                    : t('admin.importRecipe')}
                </Button>
              </div>
              <div className="text-sm text-muted-foreground">{r.description}</div>
              <div className="mt-2 text-xs text-muted-foreground">v{r.version}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Recettes locales ────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t('admin.localRecipes')}</h2>
        {isLoading && <p className="text-muted-foreground">…</p>}
        {isError && (
          <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>
        )}
        {!isLoading && !isError && !recipes?.length && (
          <p className="text-muted-foreground">{t('admin.recipesEmpty')}</p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {recipes?.map((recipe: Recipe) => (
            <div key={recipe.id} className="rounded-lg border bg-card p-4">
              <div className="mb-1 flex items-start justify-between gap-2">
                <div className="font-medium">{recipe.id}</div>
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => openEdit(recipe)}
                  >
                    {t('workspaces.actions.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive hover:text-destructive"
                    onClick={() => deleteRecipe.mutate(recipe.id)}
                    disabled={deleteRecipe.isPending}
                  >
                    {t('workspaces.actions.delete')}
                  </Button>
                </div>
              </div>
              <div className="text-sm text-muted-foreground">{recipe.description}</div>
              <div className="mt-2 text-xs text-muted-foreground">v{recipe.version}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Dialog édition recette locale ───────────────────────────── */}
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {isEditing ? t('admin.editRecipe') : t('admin.addRecipe')}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {t('admin.recipeDialogDescription')}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="r-id">{t('admin.form.recipeId')}</Label>
              <Input
                id="r-id"
                value={form.id}
                onChange={(e) => set('id', e.target.value)}
                placeholder="my-tool"
                pattern="^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$"
                required
                readOnly={isEditing}
                className={isEditing ? 'opacity-60 cursor-not-allowed' : ''}
              />
            </div>
            <div className="flex gap-4">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="r-version">{t('admin.form.version')}</Label>
                <Input
                  id="r-version"
                  value={form.version}
                  onChange={(e) => set('version', e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="r-desc">{t('admin.form.description')}</Label>
                <Input
                  id="r-desc"
                  value={form.description}
                  onChange={(e) => set('description', e.target.value)}
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t('admin.form.installScript')}</Label>
              <div
                className="bash-editor overflow-auto rounded-md border border-input bg-zinc-950 shadow-sm focus-within:ring-1 focus-within:ring-ring"
                style={{ minHeight: '220px', maxHeight: '420px' }}
              >
                <Editor
                  value={form.install_script}
                  onValueChange={(v) => set('install_script', v)}
                  highlight={(code) => {
                    const grammar = Prism.languages['bash']
                    if (!grammar) return code
                    try {
                      return Prism.highlight(code, grammar, 'bash')
                    } catch {
                      return code
                    }
                  }}
                  padding={12}
                  style={{
                    color: '#d4d4d4',
                    background: 'transparent',
                    minHeight: '220px',
                  }}
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleClose(false)}
              >
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={isPending}>
                {t('admin.form.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
