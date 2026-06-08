import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import type { Recipe } from '@/features/recipes/types'
import { useAdminRecipes, type RecipeCreateRequest } from './useAdminRecipes'

const DEFAULT_SCRIPT = '#!/usr/bin/env bash\nset -e\necho "Installing..."\n'

const EMPTY: RecipeCreateRequest = {
  id: '',
  version: '1.0.0',
  description: '',
  install_script: DEFAULT_SCRIPT,
}

export default function AdminRecipes() {
  const { t } = useTranslation()
  const { recipesQuery, deleteRecipe, addRecipe } = useAdminRecipes()
  const { data: recipes, isLoading, isError } = recipesQuery
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<RecipeCreateRequest>(EMPTY)

  function set<K extends keyof RecipeCreateRequest>(k: K, v: RecipeCreateRequest[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function handleClose(o: boolean) {
    if (!o) setForm(EMPTY)
    setOpen(o)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    addRecipe.mutate(form, { onSuccess: () => handleClose(false) })
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('admin.sharedRecipes')}</h1>
        <Button size="sm" onClick={() => setOpen(true)}>{t('admin.addRecipe')}</Button>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !recipes?.length && (
        <p className="text-muted-foreground">{t('admin.recipesEmpty')}</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {recipes?.map((recipe: Recipe) => (
          <div key={recipe.id} className="rounded-lg border bg-card p-4">
            <div className="mb-1 flex items-start justify-between gap-2">
              <div className="font-medium">{recipe.id}</div>
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
            <div className="text-sm text-muted-foreground">{recipe.description}</div>
            <div className="mt-2 text-xs text-muted-foreground">v{recipe.version}</div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('admin.addRecipe')}</DialogTitle>
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
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="r-version">{t('admin.form.version')}</Label>
              <Input
                id="r-version"
                value={form.version}
                onChange={(e) => set('version', e.target.value)}
                placeholder="1.0.0"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="r-desc">{t('admin.form.description')}</Label>
              <Input
                id="r-desc"
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                placeholder="Description courte"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="r-script">{t('admin.form.installScript')}</Label>
              <textarea
                id="r-script"
                value={form.install_script}
                onChange={(e) => set('install_script', e.target.value)}
                rows={8}
                className="min-h-[120px] w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring resize-y"
                required
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => handleClose(false)}>
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={addRecipe.isPending}>
                {t('admin.form.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
