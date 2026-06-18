import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'
import { useRecipes } from './useRecipes'
import type { Recipe } from './types'

export default function RecipeCatalog() {
  const { t } = useTranslation()
  const { data: recipes, isLoading } = useRecipes()
  const [query, setQuery] = useState('')

  const filtered = recipes?.filter((r: Recipe) => {
    const q = query.toLowerCase()
    return r.id.toLowerCase().includes(q) || r.description.toLowerCase().includes(q)
  })

  return (
    <div>
      <div className="mb-6 flex items-center gap-4">
        <h1 className="text-2xl font-semibold">{t('recipes.title')}</h1>
        <Input
          placeholder={t('recipes.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="max-w-xs"
        />
      </div>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {!isLoading && !filtered?.length && (
        <p className="text-muted-foreground">
          {query ? t('recipes.noMatch') : t('recipes.empty')}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered?.map((recipe: Recipe) => (
          <div
            key={recipe.id}
            className="rounded-lg border bg-card p-4"
          >
            <div className="mb-1 font-medium">{recipe.id}</div>
            <div className="text-sm text-muted-foreground">{recipe.description}</div>
            <div className="mt-2 text-xs text-muted-foreground">v{recipe.version}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
