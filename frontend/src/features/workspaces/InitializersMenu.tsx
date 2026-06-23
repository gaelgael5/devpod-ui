import { useTranslation } from 'react-i18next'
import { Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useWorkspaceInitializers, useRunInitializer } from './useWorkspaceInitializers'

interface Props {
  /** Nom du workspace. */
  wsName: string
  /** Le workspace est démarré (sinon l'exécution est impossible). */
  enabled: boolean
}

/**
 * Menu des actions d'initialisation (recipes `type: initialize`) du workspace.
 * Masqué si le workspace n'en déclare aucune.
 */
export default function InitializersMenu({ wsName, enabled }: Props) {
  const { t } = useTranslation()
  const { data: initializers = [] } = useWorkspaceInitializers(wsName)
  const run = useRunInitializer()

  if (initializers.length === 0) return null

  function handleRun(id: string, force: boolean) {
    toast.promise(run.mutateAsync({ wsName, id, force }), {
      loading: t('workspaces.initializers.running'),
      success: (res) =>
        res.already_applied
          ? t('workspaces.initializers.alreadyApplied')
          : t('workspaces.initializers.applied'),
      error: (e) => (e instanceof Error ? e.message : t('workspaces.initializers.failed')),
    })
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          disabled={!enabled || run.isPending}
          title={!enabled ? t('workspaces.initializers.needRunning') : undefined}
        >
          <Sparkles className="h-3.5 w-3.5" />
          {t('workspaces.initializers.button')}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">
        {initializers.map((init, idx) => (
          <div key={init.id}>
            {idx > 0 && <DropdownMenuSeparator />}
            <DropdownMenuLabel className="font-normal">
              {init.description || init.id}
            </DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => handleRun(init.id, false)}>
              {t('workspaces.initializers.run')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-muted-foreground"
              onSelect={() => handleRun(init.id, true)}
            >
              {t('workspaces.initializers.force')}
            </DropdownMenuItem>
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
