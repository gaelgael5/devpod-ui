import { useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Code2, Loader2, Mail, Play, Plus, Square, SquareTerminal, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { WorkspaceSpec, WorkspaceStatus, WorkspaceStatusValue } from './types'
import SshKeyDialog from './SshKeyDialog'
import LogDialog from './LogDialog'
import { openTerminalTab } from '@/features/terminal/openTerminalTab'
import WorkspaceActionsMenu from './WorkspaceActionsMenu'
import { CreateSessionDialogHost } from './CreateSessionDialog'
import WorkspaceSkillsDialog from '@/features/skills/WorkspaceSkillsDialog'
import { useWorkspaceSessions, useDeleteSession } from './useWorkspaceSessions'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import AddTestVmDialog from './AddTestVmDialog'
import HostServicesSection from './HostServicesSection'
import WorkspaceMessagesDialog from './WorkspaceMessagesDialog'
import AgentMessagesPanel from './AgentMessagesPanel'
import { usePendingCounts } from './useAgentMessages'
import { STATUS_TONE_CLASS } from './statusTone'
import type { TestHost } from './useTestVm'

const STATUS_CLASS: Record<WorkspaceStatusValue, string> = {
  running: STATUS_TONE_CLASS.running,
  stopped: STATUS_TONE_CLASS.stopped,
  provisioning: STATUS_TONE_CLASS.progress,
  failed: STATUS_TONE_CLASS.error,
  unknown: STATUS_TONE_CLASS.neutral,
}

interface Props {
  spec: WorkspaceSpec
  status: WorkspaceStatus
  onStop: (name: string) => void
  onDelete: (name: string, shelve: boolean) => void
  onStart?: (name: string) => void
  onRecreate?: (name: string) => void
  isStarting?: boolean
  onManageGroups?: () => void
}

export default function WorkspaceCard({ spec, status, onStop, onDelete, onStart, onRecreate, isStarting = false, onManageGroups }: Props) {
  const { t } = useTranslation()
  const [sshKeyOpen, setSshKeyOpen] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const [messagesOpen, setMessagesOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [recreateOpen, setRecreateOpen] = useState(false)
  const [addVmOpen, setAddVmOpen] = useState(false)
  const [agentMsgOpen, setAgentMsgOpen] = useState(false)
  const [addSessionOpen, setAddSessionOpen] = useState(false)
  const [skillsOpen, setSkillsOpen] = useState(false)
  // Confirmation de suppression d'une session (le tmux et ses agents meurent) :
  // on ne supprime jamais sur simple clic dans le menu.
  const [sessionToDelete, setSessionToDelete] = useState<string | null>(null)
  const deleteSession = useDeleteSession()
  // Sessions actives (polling léger, uniquement workspace running) : alimente
  // le libellé « Sessions (N) » et la liste du menu déroulant.
  const { data: sessions = [] } = useWorkspaceSessions(
    status.status === 'running' ? spec.name : undefined
  )

  function openSessionTab(session: string) {
    window.open(
      `/workspaces/${encodeURIComponent(spec.name)}/terminals?session=${encodeURIComponent(session)}`,
      '_blank',
      'noopener'
    )
  }
  // Shell direct et SSH d'une VM de test s'ouvrent aussi en onglet (comme les
  // sessions), via le terminal plein écran générique.
  const openShellTab = () =>
    openTerminalTab(`/me/workspaces/${encodeURIComponent(spec.name)}/ssh?shell=1`, `${spec.name} — shell`)
  const openTestHostTab = (host: TestHost) =>
    openTerminalTab(
      `/me/workspaces/${encodeURIComponent(spec.name)}/ssh?ssh_test=${encodeURIComponent(host.name)}`,
      host.alias,
    )
  const { data: pendingCounts } = usePendingCounts()
  const pendingCount = pendingCounts?.[spec.name] ?? 0
  const s = status.status

  return (
    <div className="rounded-lg border bg-card p-4" data-testid={`workspace-card-${spec.name}`}>
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-foreground">{spec.name}</div>
          <div className="text-xs text-muted-foreground">{spec.source}</div>
          {/* Sources git additionnelles (extra_sources) : sinon un workspace multi-repo
              n'affiche que sa source principale (le 2e dépôt semblait « perdu »). */}
          {spec.extra_sources?.map((s, i) => (
            <div key={`${s.url}-${i}`} className="text-xs text-muted-foreground/80">
              + {s.url}
            </div>
          ))}
          {spec.host && (
            <div className="text-xs text-muted-foreground/70 font-mono">{spec.host}</div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {pendingCount > 0 && (
            <button
              type="button"
              onClick={() => setAgentMsgOpen(true)}
              aria-label={t('agentMessages.badgeLabel', { count: pendingCount })}
              className="flex items-center gap-1 rounded-full border border-amber-500/50 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 hover:bg-amber-100"
            >
              <Mail className="h-3.5 w-3.5" />
              {pendingCount}
            </button>
          )}
          <Badge
            variant="outline"
            className={cn('text-xs', STATUS_CLASS[s])}
          >
            {s === 'provisioning' && '⟳ '}{t(`workspaces.status.${s}`)}
          </Badge>
        </div>
      </div>

      {agentMsgOpen && (
        <AgentMessagesPanel open onOpenChange={(o) => { if (!o) setAgentMsgOpen(false) }} />
      )}

      {spec.recipes.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {spec.recipes.map((r) => (
            <span
              key={r}
              className="rounded-sm bg-primary/10 px-2 py-0.5 text-xs text-primary"
            >
              {r}
            </span>
          ))}
        </div>
      )}

      {(s === 'provisioning' || isStarting) && (
        <div className="mb-3 h-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {s === 'running' && status.url && (
          <Button size="sm" asChild aria-label={t('workspaces.actions.openVscode')}>
            <a href={status.url} target="_blank" rel="noopener noreferrer">
              <Code2 className="h-4 w-4" />
            </a>
          </Button>
        )}
        {s === 'running' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onStop(spec.name)}
            aria-label={t('workspaces.actions.stop')}
          >
            <Square className="h-4 w-4" />
          </Button>
        )}
        {s === 'running' && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline">
                {t('workspaces.terminals.sessionsMenu', { count: sessions.length })}
                <ChevronDown className="ml-1 h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onSelect={() => setAddSessionOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                {t('workspaces.terminals.newSession')}
              </DropdownMenuItem>
              {sessions.length > 0 && <DropdownMenuSeparator />}
              {sessions.map((session) => (
                <DropdownMenuItem
                  key={session}
                  onSelect={() => openSessionTab(session)}
                  className="group/session gap-2"
                >
                  <SquareTerminal className="h-4 w-4" />
                  <span className="flex-1 truncate">{session}</span>
                  <button
                    type="button"
                    aria-label={t('workspaces.terminals.deleteSession', { name: session })}
                    className="rounded p-0.5 text-muted-foreground opacity-0 hover:text-destructive group-hover/session:opacity-100"
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); setSessionToDelete(session) }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        {s === 'stopped' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onStart?.(spec.name)}
            disabled={!onStart || isStarting}
            aria-label={t('workspaces.actions.start')}
          >
            {isStarting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          </Button>
        )}
        {(s === 'stopped' || s === 'unknown' || s === 'failed') && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setRecreateOpen(true)}
            disabled={!onRecreate}
          >
            {t('workspaces.actions.recreate')}
          </Button>
        )}
        {(s === 'stopped' || s === 'unknown' || s === 'failed' || s === 'provisioning') && (
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => setConfirmOpen(true)}
          >
            {t('workspaces.actions.delete')}
          </Button>
        )}
        {s === 'failed' && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onStart?.(spec.name)}
            disabled={!onStart || isStarting}
          >
            {isStarting && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
            {t('workspaces.actions.retry')}
          </Button>
        )}
        {/* Aligné à droite, sous le menu ⋮ des machines de test */}
        <div className="ml-auto">
          <WorkspaceActionsMenu
            wsName={spec.name}
            running={s === 'running'}
            agents={spec.agents ?? []}
            onAddVm={() => setAddVmOpen(true)}
            onOpenShell={openShellTab}
            onShowSshKey={spec.ssh_key ? () => setSshKeyOpen(true) : undefined}
            onOpenMessages={() => setMessagesOpen(true)}
            onOpenLogs={() => setLogsOpen(true)}
            onManageGroups={onManageGroups}
            onManageSkills={() => setSkillsOpen(true)}
          />
        </div>
      </div>

      <HostServicesSection wsName={spec.name} enabled={s === 'running'} onOpenSsh={openTestHostTab} />

      {spec.ssh_key && (
        <SshKeyDialog
          workspaceName={spec.name}
          open={sshKeyOpen}
          onOpenChange={setSshKeyOpen}
        />
      )}
      {addSessionOpen && (
        <CreateSessionDialogHost
          wsName={spec.name}
          onClose={() => setAddSessionOpen(false)}
          onCreate={openSessionTab}
        />
      )}
      {skillsOpen && (
        <WorkspaceSkillsDialog wsName={spec.name} onClose={() => setSkillsOpen(false)} />
      )}
      <Dialog open={sessionToDelete !== null} onOpenChange={(o) => { if (!o) setSessionToDelete(null) }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.terminals.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {t('workspaces.terminals.deleteDescription', { name: sessionToDelete ?? '' })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="ghost" size="sm" onClick={() => setSessionToDelete(null)}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={deleteSession.isPending}
              onClick={() => {
                const name = sessionToDelete
                if (!name) return
                deleteSession.mutate(
                  { wsName: spec.name, sessionName: name },
                  {
                    onSuccess: () => toast.success(t('workspaces.terminals.deleted', { name })),
                    onError: (e) => toast.error(e.message),
                  },
                )
                setSessionToDelete(null)
              }}
            >
              {t('workspaces.terminals.confirmDelete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AddTestVmDialog
        wsName={spec.name}
        open={addVmOpen}
        onClose={() => setAddVmOpen(false)}
      />
      <LogDialog
        workspaceName={spec.name}
        open={logsOpen}
        onOpenChange={setLogsOpen}
        status={status.status}
      />
      <WorkspaceMessagesDialog
        workspaceName={spec.name}
        open={messagesOpen}
        onOpenChange={setMessagesOpen}
      />
      <Dialog open={recreateOpen} onOpenChange={setRecreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.confirm.recreateTitle')}</DialogTitle>
            <DialogDescription>
              {t('workspaces.confirm.recreateDescription', { name: spec.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="ghost" size="sm" onClick={() => setRecreateOpen(false)}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setRecreateOpen(false)
                onRecreate?.(spec.name)
              }}
            >
              {t('workspaces.confirm.confirmRecreate')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspaces.confirm.deleteTitle')}</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2">
                <p>{t('workspaces.confirm.deleteDescription', { name: spec.name })}</p>
                <p>{t('workspaces.confirm.deleteShelveChoice')}</p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button variant="ghost" size="sm" onClick={() => setConfirmOpen(false)}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setConfirmOpen(false)
                onDelete(spec.name, true)
              }}
            >
              {t('workspaces.confirm.confirmShelve')}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setConfirmOpen(false)
                onDelete(spec.name, false)
              }}
            >
              {t('workspaces.confirm.confirmForce')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
