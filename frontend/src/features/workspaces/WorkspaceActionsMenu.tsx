import { useTranslation } from 'react-i18next'
import {
  FileText, FolderOpen, Key, MessageSquare, MoreVertical, PlusCircle, TerminalSquare,
} from 'lucide-react'
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
  wsName: string
  /** Workspace running : shell SSH, initializers et VM de test disponibles. */
  running: boolean
  onAddVm: () => void
  onOpenShell: () => void
  /** Absent si le workspace n'a pas de clé SSH générée. */
  onShowSshKey?: () => void
  onOpenMessages: () => void
  onOpenLogs: () => void
  onManageGroups?: () => void
}

/** Menu "⋮" du workspace : SSH, messages, logs, groupes, initializers, VM de test. */
export default function WorkspaceActionsMenu({
  wsName, running, onAddVm, onOpenShell, onShowSshKey,
  onOpenMessages, onOpenLogs, onManageGroups,
}: Props) {
  const { t } = useTranslation()
  const { data: initializers = [] } = useWorkspaceInitializers(running ? wsName : undefined)
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
        {running && (
          <DropdownMenuItem className="gap-2" onSelect={onOpenShell}>
            <TerminalSquare className="h-3.5 w-3.5" />
            {t('workspaces.ssh.shellButton')}
          </DropdownMenuItem>
        )}
        {onShowSshKey && (
          <DropdownMenuItem className="gap-2" onSelect={onShowSshKey}>
            <Key className="h-3.5 w-3.5" />
            {t('workspaces.sshKey.button')}
          </DropdownMenuItem>
        )}
        {(running || onShowSshKey) && <DropdownMenuSeparator />}
        <DropdownMenuItem className="gap-2" onSelect={onOpenMessages}>
          <MessageSquare className="h-3.5 w-3.5" />
          {t('workspaces.messages.button')}
        </DropdownMenuItem>
        <DropdownMenuItem className="gap-2" onSelect={onOpenLogs}>
          <FileText className="h-3.5 w-3.5" />
          {t('workspaces.logs.button')}
        </DropdownMenuItem>
        {onManageGroups && (
          <DropdownMenuItem className="gap-2" onSelect={onManageGroups}>
            <FolderOpen className="h-3.5 w-3.5" />
            {t('groups.manage')}
          </DropdownMenuItem>
        )}
        {running && (
          <>
            <DropdownMenuSeparator />
            <InitializerMenuItems initializers={initializers} onRun={handleRun} />
            {initializers.length > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem className="gap-2" onSelect={onAddVm}>
              <PlusCircle className="h-3.5 w-3.5" />
              {t('workspaces.testVm.btn')}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
