import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
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
import { useSetWorkspaceGroups } from './useWorkspaceGroups'
import type { WorkspaceSpec } from './types'
import type { WorkspaceGroup } from './useWorkspaceGroups'

interface Props {
  workspace: WorkspaceSpec
  groups: WorkspaceGroup[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function WorkspaceGroupsDialog({ workspace, groups, open, onOpenChange }: Props) {
  const { t } = useTranslation()
  const setGroups = useSetWorkspaceGroups()
  const [selected, setSelected] = useState<Set<string>>(
    new Set(workspace.groups ?? []),
  )

  function toggle(name: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  function handleSave() {
    setGroups.mutate(
      { workspaceName: workspace.name, groups: Array.from(selected) },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('groups.assignTitle', { name: workspace.name })}</DialogTitle>
          <DialogDescription>{t('groups.assignDescription')}</DialogDescription>
        </DialogHeader>

        {groups.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('groups.noGroupsYet')}</p>
        ) : (
          <div className="flex flex-col gap-2 max-h-64 overflow-y-auto py-1">
            {groups.map((g) => {
              const checked = selected.has(g.name)
              return (
                <button
                  key={g.id}
                  className={cn(
                    'flex items-center gap-3 rounded-md border px-3 py-2 text-sm transition-colors text-left',
                    checked
                      ? 'border-primary bg-primary/5 text-foreground'
                      : 'border-border bg-card text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                  onClick={() => toggle(g.name)}
                >
                  <span
                    className={cn(
                      'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                      checked ? 'border-primary bg-primary text-primary-foreground' : 'border-border',
                    )}
                  >
                    {checked && <Check className="h-3 w-3" />}
                  </span>
                  {g.name}
                </button>
              )
            })}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('groups.cancel')}
          </Button>
          <Button onClick={handleSave} disabled={setGroups.isPending || groups.length === 0}>
            {t('groups.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
