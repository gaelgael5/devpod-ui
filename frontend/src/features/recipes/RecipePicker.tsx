import { cn } from '@/lib/utils'
import type { Recipe } from './types'

interface Props {
  recipes: Recipe[]
  selected: string[]
  onChange: (selected: string[]) => void
}

export default function RecipePicker({ recipes, selected, onChange }: Props) {
  function toggle(id: string) {
    if (selected.includes(id)) {
      onChange(selected.filter((r) => r !== id))
    } else {
      onChange([...selected, id])
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      {recipes.map((recipe) => {
        const isSelected = selected.includes(recipe.id)
        return (
          <button
            key={recipe.id}
            type="button"
            data-selected={isSelected}
            onClick={() => toggle(recipe.id)}
            className={cn(
              'rounded-md border px-3 py-1 text-sm transition-colors',
              isSelected
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border bg-background text-muted-foreground hover:border-primary/50 hover:text-foreground'
            )}
            title={recipe.description}
          >
            {recipe.id}
          </button>
        )
      })}
    </div>
  )
}
