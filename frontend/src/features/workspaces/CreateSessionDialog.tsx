import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  useWorkspaceSessions,
  useWorkspaceStartRecipes,
  useCreateSession,
  type WorkspaceStartRecipe,
} from './useWorkspaceSessions'
import { SESSION_NAME_RE, computeNextName } from './sessionName'

// ── Dialog "Nouvelle session" ─────────────────────────────────────────────────

interface CreateDialogProps {
  wsName: string
  sessions: string[]
  startRecipes: WorkspaceStartRecipe[]
  onClose: () => void
  onCreate: (name: string) => void
}

export default function CreateSessionDialog({ wsName, sessions, startRecipes, onClose, onCreate }: CreateDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState(() => computeNextName(sessions, wsName))
  const [nameError, setNameError] = useState('')
  const nameEdited = useRef(false)
  const [startRecipe, setStartRecipe] = useState(() => startRecipes[0]?.id ?? '')
  const create = useCreateSession()

  useEffect(() => {
    if (!nameEdited.current) setName(computeNextName(sessions, wsName))
  }, [sessions, wsName])

  function handleSubmit() {
    if (!SESSION_NAME_RE.test(name)) {
      setNameError(t('workspaces.terminals.nameHint'))
      return
    }
    setNameError('')
    create.mutate(
      { wsName, name, startRecipe: startRecipe || undefined },
      {
        onSuccess: () => { onCreate(name); onClose() },
        onError: (err) => toast.error(err.message),
      }
    )
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('workspaces.terminals.createTitle')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="session-name">{t('workspaces.terminals.nameLabel')}</Label>
            <Input
              id="session-name"
              value={name}
              onChange={(e) => { nameEdited.current = true; setName(e.target.value); setNameError('') }}
              placeholder={t('workspaces.terminals.namePlaceholder')}
              autoFocus
              onKeyDown={(e) => { if (e.key === 'Enter' && name) handleSubmit() }}
            />
            {nameError && (
              <p role="alert" className="mt-1 text-sm text-destructive">
                {nameError}
              </p>
            )}
          </div>
          {startRecipes.length === 1 && (
            <label className="flex items-center gap-2 cursor-pointer select-none text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 cursor-pointer accent-primary"
                checked={startRecipe !== ''}
                onChange={(e) => setStartRecipe(e.target.checked ? startRecipes[0].id : '')}
              />
              <span>
                {startRecipes[0].id}
                {startRecipes[0].description && (
                  <span className="text-muted-foreground ml-1">— {startRecipes[0].description}</span>
                )}
              </span>
            </label>
          )}
          {startRecipes.length > 1 && (
            <div className="space-y-1.5">
              <Label htmlFor="session-recipe">{t('workspaces.terminals.startRecipeLabel')}</Label>
              <select
                id="session-recipe"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={startRecipe}
                onChange={(e) => setStartRecipe(e.target.value)}
              >
                <option value="">{t('workspaces.terminals.startRecipeNone')}</option>
                {startRecipes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.id}{r.description ? ` — ${r.description}` : ''}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t('workspaces.terminals.cancel')}
          </Button>
          <Button onClick={handleSubmit} disabled={!name || create.isPending}>
            {create.isPending ? '…' : t('workspaces.terminals.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Variante autonome pour la carte workspace : charge elle-même sessions et
 start recipes. À monter uniquement quand le dialog est ouvert — les hooks
 (dont le polling 5 s des sessions) ne vivent que le temps du dialog. */
export function CreateSessionDialogHost({
  wsName,
  onClose,
  onCreate,
}: {
  wsName: string
  onClose: () => void
  onCreate: (name: string) => void
}) {
  const { data: sessions = [] } = useWorkspaceSessions(wsName)
  const { data: startRecipes = [] } = useWorkspaceStartRecipes(wsName)
  return (
    <CreateSessionDialog
      wsName={wsName}
      sessions={sessions}
      startRecipes={startRecipes}
      onClose={onClose}
      onCreate={onCreate}
    />
  )
}
