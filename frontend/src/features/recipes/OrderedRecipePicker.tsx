import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { Recipe } from './types'

interface Props {
  recipes: Recipe[]
  selected: string[]
  onChange: (selected: string[]) => void
}

export default function OrderedRecipePicker({ recipes, selected, onChange }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')

  const selectedSet = useMemo(() => new Set(selected), [selected])
  const recipeById = useMemo(() => new Map(recipes.map((r) => [r.id, r])), [recipes])
  const available = useMemo(() => recipes.filter((r) => !selectedSet.has(r.id)), [recipes, selectedSet])
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return available
    return available.filter(
      (r) => r.id.toLowerCase().includes(q) || r.description?.toLowerCase().includes(q)
    )
  }, [available, filter])

  function add(id: string) {
    onChange([...selected, id])
    setOpen(false)
    setFilter('')
  }

  function handleOpenChange(o: boolean) {
    setOpen(o)
    if (!o) setFilter('')
  }

  function remove(id: string) {
    onChange(selected.filter((r) => r !== id))
  }

  return (
    <div className="flex flex-col gap-2">
      {selected.length > 0 && (
        <ol className="flex flex-col gap-1">
          {selected.map((id, idx) => {
            const recipe = recipeById.get(id)
            return (
              <li
                key={id}
                className="flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm"
              >
                <span className="w-5 shrink-0 text-right text-xs text-muted-foreground">
                  {idx + 1}.
                </span>
                <span className="flex-1 font-medium">{id}</span>
                {recipe?.description && (
                  <span className="max-w-[180px] truncate text-xs text-muted-foreground">
                    {recipe.description}
                  </span>
                )}
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6 shrink-0"
                  onClick={() => remove(id)}
                  aria-label={t('workspaces.form.removeRecipeLabel', { id })}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </li>
            )
          })}
        </ol>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => setOpen(true)}
      >
        <Plus className="mr-1 h-3.5 w-3.5" />
        {t('workspaces.form.addRecipe')}
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.form.addRecipe')}</DialogTitle>
            <DialogDescription className="sr-only">
              {t('workspaces.form.addRecipe')}
            </DialogDescription>
          </DialogHeader>
          {available.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('workspaces.form.noMoreRecipes')}
            </p>
          ) : (
            <>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  autoFocus
                  placeholder={t('workspaces.form.filterRecipes')}
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="pl-8 text-sm"
                />
              </div>
              <div className="flex max-h-72 flex-col gap-2 overflow-y-auto">
                {filtered.length === 0 ? (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    {t('workspaces.form.noRecipeMatch')}
                  </p>
                ) : (
                  filtered.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => add(r.id)}
                      className="flex flex-col gap-0.5 rounded-md border bg-card px-3 py-2 text-left transition-colors hover:bg-accent"
                    >
                      <span className="text-sm font-medium">{r.id}</span>
                      {r.description && (
                        <span className="text-xs text-muted-foreground">
                          {r.description}
                        </span>
                      )}
                    </button>
                  ))
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
