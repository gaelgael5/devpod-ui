import { useTranslation } from 'react-i18next'
import { MoreVertical, PlusCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useWorkspaceInitializers, useRunInitializerWithToast } from './useWorkspaceInitializers'
import InitializerMenuItems from './InitializerMenuItems'

interface Props {
  /** Nom du workspace (uniquement rendu quand il tourne, cf. WorkspaceCard). */
  wsName: string
  onAddVm: () => void
}

/** Menu "⋮" du workspace : actions d'initialisation + ajout d'une VM de test. */
export default function WorkspaceActionsMenu({ wsName, onAddVm }: Props) {
  const { t } = useTranslation()
  const { data: initializers = [] } = useWorkspaceInitializers(wsName)
  const { handleRun } = useRunInitializerWithToast(wsName)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0"
          aria-label={t('workspaces.actionsMenu')}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <InitializerMenuItems initializers={initializers} onRun={handleRun} />
        {initializers.length > 0 && <DropdownMenuSeparator />}
        <DropdownMenuItem className="gap-2" onSelect={onAddVm}>
          <PlusCircle className="h-3.5 w-3.5" />
          {t('workspaces.testVm.btn')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
