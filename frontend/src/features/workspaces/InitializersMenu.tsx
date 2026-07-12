import { useTranslation } from 'react-i18next'
import { Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
} from '@/components/ui/dropdown-menu'
import { useWorkspaceInitializers, useRunInitializerWithToast } from './useWorkspaceInitializers'
import InitializerMenuItems from './InitializerMenuItems'

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
  const { handleRun, isPending } = useRunInitializerWithToast(wsName)

  if (initializers.length === 0) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          className="gap-1.5"
          disabled={!enabled || isPending}
          title={!enabled ? t('workspaces.initializers.needRunning') : undefined}
        >
          <Sparkles className="h-3.5 w-3.5" />
          {t('workspaces.initializers.button')}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">
        <InitializerMenuItems initializers={initializers} onRun={handleRun} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
