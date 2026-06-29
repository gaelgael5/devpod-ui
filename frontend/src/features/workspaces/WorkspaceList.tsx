import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Pencil, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useWorkspaces } from './useWorkspaces'
import { useWorkspaceStatus } from './useWorkspaceStatus'
import { useWorkspaceOps } from './useWorkspaceOps'
import {
  useWorkspaceGroups,
  useCreateGroup,
  useRenameGroup,
  useDeleteGroup,
} from './useWorkspaceGroups'
import WorkspaceCard from './WorkspaceCard'
import WorkspaceGroupsDialog from './WorkspaceGroupsDialog'
import type { WorkspaceSpec } from './types'

function WorkspaceRow({ spec, onManageGroups }: { spec: WorkspaceSpec; onManageGroups: () => void }) {
  const { data: status } = useWorkspaceStatus(spec.name)
  const { stopWorkspace, deleteWorkspace, createWorkspace, recreateWorkspace } = useWorkspaceOps()
  const liveStatus = status ?? { ws_id: `?-${spec.name}`, status: 'unknown' as const }

  return (
    <WorkspaceCard
      spec={spec}
      status={liveStatus}
      onStop={(n) => stopWorkspace.mutate(n)}
      onDelete={(n, shelve) => deleteWorkspace.mutate({ name: n, shelve })}
      onStart={(n) =>
        createWorkspace.mutate({
          name: n,
          sources: [
            { url: spec.source, branch: spec.branch, credential: spec.git_credential },
            ...spec.extra_sources.map(s => ({ url: s.url, branch: s.branch, credential: s.git_credential })),
          ],
          host: spec.host,
          recipes: spec.recipes,
        })
      }
      onRecreate={(n) => recreateWorkspace.mutate(n)}
      isStarting={createWorkspace.isPending}
      onManageGroups={onManageGroups}
    />
  )
}

interface GroupSectionProps {
  title: string
  workspaces: WorkspaceSpec[]
  groupId?: number
  onRename?: (id: number, current: string) => void
  onDelete?: (id: number, name: string) => void
  onManageGroups: (ws: WorkspaceSpec) => void
}

function GroupSection({
  title,
  workspaces,
  groupId,
  onRename,
  onDelete,
  onManageGroups,
}: GroupSectionProps) {
  const { t } = useTranslation()
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="flex flex-col gap-3">
      <div className="group/header flex items-center gap-2">
        <button
          className="flex items-center gap-1.5 text-sm font-semibold text-foreground hover:text-primary transition-colors"
          onClick={() => setCollapsed((c) => !c)}
          aria-expanded={!collapsed}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
          {title}
          <span className="text-xs font-normal text-muted-foreground ml-1">
            ({workspaces.length})
          </span>
        </button>
        {groupId !== undefined && onRename && onDelete && (
          <div className="flex gap-0.5 ml-auto opacity-0 group-hover/header:opacity-100 transition-opacity">
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              onClick={() => onRename(groupId, title)}
              aria-label={t('groups.rename')}
            >
              <Pencil className="h-3 w-3" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6 text-destructive hover:text-destructive"
              onClick={() => onDelete(groupId, title)}
              aria-label={t('groups.delete')}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>
      {!collapsed && workspaces.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {workspaces.map((ws) => (
            <WorkspaceRow
              key={ws.name}
              spec={ws}
              onManageGroups={() => onManageGroups(ws)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function WorkspaceList() {
  const { t } = useTranslation()
  const { data: workspaces, isLoading, isError } = useWorkspaces()
  const { data: groups = [] } = useWorkspaceGroups()
  const createGroup = useCreateGroup()
  const renameGroup = useRenameGroup()
  const deleteGroup = useDeleteGroup()

  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [renameTarget, setRenameTarget] = useState<{ id: number; current: string } | null>(null)
  const [renameName, setRenameName] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null)
  const [groupsTarget, setGroupsTarget] = useState<WorkspaceSpec | null>(null)

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    const name = createName.trim()
    if (!name) return
    createGroup.mutate(name, {
      onSuccess: () => {
        setCreateOpen(false)
        setCreateName('')
      },
    })
  }

  function handleRename(e: React.FormEvent) {
    e.preventDefault()
    if (!renameTarget) return
    const name = renameName.trim()
    if (!name) return
    renameGroup.mutate(
      { id: renameTarget.id, name },
      { onSuccess: () => setRenameTarget(null) },
    )
  }

  function handleDelete() {
    if (!deleteTarget) return
    deleteGroup.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) })
  }

  function openRename(id: number, current: string) {
    setRenameTarget({ id, current })
    setRenameName(current)
  }

  const allWorkspaces = workspaces ?? []

  // Build group → workspaces mapping
  const groupedMap = new Map<string, WorkspaceSpec[]>()
  for (const g of groups) groupedMap.set(g.name, [])
  for (const ws of allWorkspaces) {
    for (const gName of ws.groups ?? []) {
      if (!groupedMap.has(gName)) groupedMap.set(gName, [])
      groupedMap.get(gName)!.push(ws)
    }
  }
  const ungrouped = allWorkspaces.filter((ws) => !ws.groups?.length)

  return (
    <div>
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="mb-6 flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-semibold flex-1">{t('workspaces.title')}</h1>
        <Button size="sm" variant="outline" onClick={() => setCreateOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />
          {t('groups.new')}
        </Button>
        <Button asChild>
          <Link to="/workspaces/new">{t('workspaces.new')}</Link>
        </Button>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}

      {!isLoading && !isError && allWorkspaces.length === 0 && (
        <p className="text-muted-foreground">{t('workspaces.empty')}</p>
      )}

      {/* ── Sections groupées ────────────────────────────────── */}
      <div className="flex flex-col gap-8">
        {groups.map((g) => (
          <GroupSection
            key={g.id}
            title={g.name}
            groupId={g.id}
            workspaces={groupedMap.get(g.name) ?? []}
            onRename={openRename}
            onDelete={(id, name) => setDeleteTarget({ id, name })}
            onManageGroups={(ws) => setGroupsTarget(ws)}
          />
        ))}

        {/* Workspaces sans groupe */}
        {ungrouped.length > 0 && (
          <GroupSection
            title={t('groups.ungrouped')}
            workspaces={ungrouped}
            onManageGroups={(ws) => setGroupsTarget(ws)}
          />
        )}
      </div>

      {/* ── Dialog : créer un groupe ─────────────────────────── */}
      <Dialog open={createOpen} onOpenChange={(o) => { setCreateOpen(o); if (!o) setCreateName('') }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('groups.createTitle')}</DialogTitle>
            <DialogDescription className="sr-only">{t('groups.createTitle')}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="flex flex-col gap-4">
            <Input
              autoFocus
              placeholder={t('groups.namePlaceholder')}
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              maxLength={50}
            />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>
                {t('groups.cancel')}
              </Button>
              <Button type="submit" disabled={!createName.trim() || createGroup.isPending}>
                {t('groups.create')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Dialog : renommer un groupe ──────────────────────── */}
      <Dialog open={renameTarget !== null} onOpenChange={(o) => !o && setRenameTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('groups.renameTitle')}</DialogTitle>
            <DialogDescription className="sr-only">{t('groups.renameTitle')}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleRename} className="flex flex-col gap-4">
            <Input
              autoFocus
              value={renameName}
              onChange={(e) => setRenameName(e.target.value)}
              maxLength={50}
            />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setRenameTarget(null)}>
                {t('groups.cancel')}
              </Button>
              <Button type="submit" disabled={!renameName.trim() || renameGroup.isPending}>
                {t('groups.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Dialog : confirmer suppression groupe ────────────── */}
      <Dialog open={deleteTarget !== null} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('groups.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {t('groups.deleteDescription', { name: deleteTarget?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              {t('groups.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteGroup.isPending}
            >
              {t('groups.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Dialog : gérer les groupes d'un workspace ────────── */}
      {groupsTarget && (
        <WorkspaceGroupsDialog
          workspace={groupsTarget}
          groups={groups}
          open={true}
          onOpenChange={(o) => { if (!o) setGroupsTarget(null) }}
        />
      )}
    </div>
  )
}
