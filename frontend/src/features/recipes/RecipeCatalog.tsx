import { useTranslation } from 'react-i18next'
import { useRecipes } from './useRecipes'

export default function RecipeCatalog() {
  const { t } = useTranslation()
  const { data: recipes, isLoading } = useRecipes()

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">{t('recipes.title')}</h1>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {!isLoading && !recipes?.length && (
        <p className="text-muted-foreground">{t('recipes.empty')}</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {recipes?.map((recipe) => (
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
