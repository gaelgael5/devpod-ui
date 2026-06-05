import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { useAdminRecipes } from './useAdminRecipes'

export default function AdminRecipes() {
  const { t } = useTranslation()
  const { recipesQuery, deleteRecipe } = useAdminRecipes()
  const { data: recipes, isLoading } = recipesQuery

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">{t('admin.sharedRecipes')}</h1>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {!isLoading && !recipes?.length && (
        <p className="text-muted-foreground">{t('admin.recipesEmpty')}</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {recipes?.map((recipe) => (
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
    </div>
  )
}
