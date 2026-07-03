import { useTranslation } from 'react-i18next'
import {
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import type { WorkspaceInitializer } from './useWorkspaceInitializers'

interface Props {
  initializers: WorkspaceInitializer[]
  onRun: (id: string, force: boolean) => void
}

/** Items "Run"/"Force" par initializer — à placer dans un `DropdownMenuContent` existant. */
export default function InitializerMenuItems({ initializers, onRun }: Props) {
  const { t } = useTranslation()

  return (
    <>
      {initializers.map((init, idx) => (
        <div key={init.id}>
          {idx > 0 && <DropdownMenuSeparator />}
          <DropdownMenuLabel className="font-normal">
            {init.description || init.id}
          </DropdownMenuLabel>
          <DropdownMenuItem onSelect={() => onRun(init.id, false)}>
            {t('workspaces.initializers.run')}
          </DropdownMenuItem>
          <DropdownMenuItem
            className="text-muted-foreground"
            onSelect={() => onRun(init.id, true)}
          >
            {t('workspaces.initializers.force')}
          </DropdownMenuItem>
        </div>
      ))}
    </>
  )
}
