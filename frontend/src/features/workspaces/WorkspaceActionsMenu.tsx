import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  Bot, FileText, FolderOpen, Key, MessageSquare, MoreVertical, PlusCircle, Sparkles, TerminalSquare,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
  DropdownMenuCheckboxItem,
} from '@/components/ui/dropdown-menu'
import { useAgentTypes } from '@/features/mcp/api'
import { useWorkspaceInitializers, useRunInitializerWithToast } from './useWorkspaceInitializers'
import InitializerMenuItems from './InitializerMenuItems'
import { useWorkspaceOps } from './useWorkspaceOps'

interface Props {
  wsName: string
  /** Workspace running : shell SSH, initializers et VM de test disponibles. */
  running: boolean
  /** Ids d'agent_types actuellement mappés (spec 35) pour pré-cocher le sous-menu. */
  agents?: string[]
  onAddVm: () => void
  onOpenShell: () => void
  /** Absent si le workspace n'a pas de clé SSH générée. */
  onShowSshKey?: () => void
  onOpenMessages: () => void
  onOpenLogs: () => void
  onManageGroups?: () => void
  /** Gestion des skills placées dans le workspace (running uniquement). */
  onManageSkills?: () => void
}

/** Menu "⋮" du workspace : SSH, messages, logs, groupes, initializers, VM de test, agents MCP. */
export default function WorkspaceActionsMenu({
  wsName, running, agents = [], onAddVm, onOpenShell, onShowSshKey,
  onOpenMessages, onOpenLogs, onManageGroups, onManageSkills,
}: Props) {
  const { t } = useTranslation()
  const { data: initializers = [] } = useWorkspaceInitializers(running ? wsName : undefined)
  const { handleRun } = useRunInitializerWithToast(wsName)
  const { data: agentTypes = [] } = useAgentTypes()
  const { updateWorkspaceAgents } = useWorkspaceOps()

  const toggleAgent = (agentId: string, checked: boolean) => {
    const next = checked
      ? [...agents, agentId]
      : agents.filter((a) => a !== agentId)
    updateWorkspaceAgents.mutate(
      { name: wsName, agents: next },
      { onSuccess: () => toast.success(t('workspaces.agentsMenu.saved')) },
    )
  }

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
        {running && (
          <DropdownMenuItem className="gap-2" onSelect={onAddVm}>
            <PlusCircle className="h-3.5 w-3.5" />
            {t('workspaces.testVm.btn')}
          </DropdownMenuItem>
        )}
        {running && onManageSkills && (
          <DropdownMenuItem className="gap-2" onSelect={onManageSkills}>
            <Sparkles className="h-3.5 w-3.5" />
            {t('workspaces.skillsMenu')}
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
        {agentTypes.length > 0 && (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="gap-2">
              <Bot className="h-3.5 w-3.5" />
              {t('workspaces.agentsMenu.label')}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {agentTypes.map((a) => (
                <DropdownMenuCheckboxItem
                  key={a.id}
                  checked={agents.includes(a.id)}
                  onSelect={(e) => e.preventDefault()}
                  onCheckedChange={(checked) => toggleAgent(a.id, checked)}
                >
                  {a.label}
                </DropdownMenuCheckboxItem>
              ))}
              <DropdownMenuSeparator />
              <p className="px-2 py-1.5 text-xs text-muted-foreground">
                {t('workspaces.agentsMenu.hint')}
              </p>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}
        {running && initializers.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <InitializerMenuItems initializers={initializers} onRun={handleRun} />
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
