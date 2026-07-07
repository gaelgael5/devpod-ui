import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  useAdminAgentTypes,
  type AgentMode,
  type AgentTypeAdmin,
  type AgentTypeBody,
} from './useAdminAgentTypes'

const EMPTY_FORM: AgentTypeBody = {
  id: '',
  label: '',
  filename: '',
  template: '',
  target_path: '',
  mode: 'replace',
  enabled: true,
}

/** Dialog création / édition d'un type d'agent (spec 35). */
function AgentTypeFormDialog({
  agentType,
  open,
  onClose,
}: {
  agentType: AgentTypeAdmin | null
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { addType, updateType, preview } = useAdminAgentTypes()
  const isNew = agentType === null

  const [form, setForm] = useState<AgentTypeBody>(
    agentType
      ? {
          id: agentType.id,
          label: agentType.label,
          filename: agentType.filename,
          template: agentType.template,
          target_path: agentType.target_path,
          mode: agentType.mode,
          enabled: agentType.enabled,
        }
      : EMPTY_FORM,
  )
  const [previewContent, setPreviewContent] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const isPending = addType.isPending || updateType.isPending

  function set<K extends keyof AgentTypeBody>(key: K, value: AgentTypeBody[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function close() {
    setPreviewContent(null)
    setPreviewError(null)
    addType.reset()
    updateType.reset()
    onClose()
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const mutation = isNew ? addType : updateType
    mutation.mutate(form, {
      onSuccess: close,
      onError: (err) => toast.error(err instanceof Error ? err.message : t('errors.generic')),
    })
  }

  async function handlePreview() {
    setPreviewContent(null)
    setPreviewError(null)
    try {
      const res = await preview.mutateAsync({ id: form.id, template: form.template })
      setPreviewContent(res.content)
    } catch (err: unknown) {
      setPreviewError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isNew
              ? t('admin.agentTypes.createTitle')
              : `${t('admin.agentTypes.editTitle')} — ${form.id}`}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-3">
          {isNew && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="at-id">{t('admin.agentTypes.id')}</Label>
              <Input
                id="at-id"
                value={form.id}
                onChange={(e) => set('id', e.target.value)}
                placeholder="claude"
                pattern="^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$"
                required
                autoFocus
              />
              <p className="text-xs text-muted-foreground">{t('admin.agentTypes.idHint')}</p>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="at-label">{t('admin.agentTypes.label')}</Label>
            <Input
              id="at-label"
              value={form.label}
              onChange={(e) => set('label', e.target.value)}
              placeholder="Claude Code"
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="at-filename">{t('admin.agentTypes.filename')}</Label>
            <Input
              id="at-filename"
              value={form.filename}
              onChange={(e) => set('filename', e.target.value)}
              placeholder=".mcp.json"
              className="font-mono"
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="at-target-path">{t('admin.agentTypes.targetPath')}</Label>
            <Input
              id="at-target-path"
              value={form.target_path}
              onChange={(e) => set('target_path', e.target.value)}
              placeholder="{{ project_root }}/.mcp.json"
              className="font-mono"
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="at-mode">{t('admin.agentTypes.mode')}</Label>
            <Select value={form.mode} onValueChange={(v) => set('mode', v as AgentMode)}>
              <SelectTrigger id="at-mode" className="w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="replace">{t('admin.agentTypes.modeReplace')}</SelectItem>
                <SelectItem value="merge">{t('admin.agentTypes.modeMerge')}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {form.mode === 'merge'
                ? t('admin.agentTypes.modeMergeHint')
                : t('admin.agentTypes.modeReplaceHint')}
            </p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="at-template">{t('admin.agentTypes.template')}</Label>
            <Textarea
              id="at-template"
              value={form.template}
              onChange={(e) => set('template', e.target.value)}
              rows={10}
              className="font-mono text-xs"
              spellCheck={false}
            />
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="at-enabled"
              checked={form.enabled}
              onCheckedChange={(v) => set('enabled', v)}
            />
            <Label htmlFor="at-enabled" className="cursor-pointer font-normal">
              {t('admin.agentTypes.enabled')}
            </Label>
          </div>

          <div className="flex flex-col gap-2">
            <div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handlePreview}
                disabled={preview.isPending || !form.id.trim()}
              >
                {t('admin.agentTypes.previewBtn')}
              </Button>
            </div>
            {previewError && (
              <pre className="whitespace-pre-wrap rounded-md bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
                {previewError}
              </pre>
            )}
            {previewContent !== null && (
              <pre className="whitespace-pre-wrap rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs">
                {previewContent}
              </pre>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={close}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Confirmation de suppression — affiche le detail du 409 si le type est référencé. */
function DeleteAgentTypeDialog({
  agentType,
  onClose,
}: {
  agentType: AgentTypeAdmin | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { deleteType } = useAdminAgentTypes()
  const [error, setError] = useState<string | null>(null)

  function close() {
    setError(null)
    deleteType.reset()
    onClose()
  }

  function confirm() {
    if (!agentType) return
    setError(null)
    deleteType.mutate(agentType.id, {
      onSuccess: close,
      onError: (err) => setError(err instanceof Error ? err.message : t('errors.generic')),
    })
  }

  return (
    <Dialog open={agentType !== null} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('admin.agentTypes.deleteTitle', { id: agentType?.id })}</DialogTitle>
          <DialogDescription>{t('admin.agentTypes.deleteWarning')}</DialogDescription>
        </DialogHeader>
        {error && (
          <pre className="whitespace-pre-wrap rounded-md bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
            {error}
          </pre>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button variant="destructive" disabled={deleteType.isPending} onClick={confirm}>
            {t('common.delete')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function AdminAgentTypes() {
  const { t } = useTranslation()
  const { typesQuery } = useAdminAgentTypes()
  const { data: types, isLoading, isError } = typesQuery

  const [createOpen, setCreateOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<AgentTypeAdmin | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<AgentTypeAdmin | null>(null)

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('admin.agentTypes.title')}</h1>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          {t('admin.agentTypes.add')}
        </Button>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !types?.length && (
        <p className="text-muted-foreground">{t('admin.agentTypes.empty')}</p>
      )}
      {types && types.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.agentTypes.id')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.agentTypes.label')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.agentTypes.filename')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.agentTypes.targetPath')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.agentTypes.mode')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.agentTypes.enabled')}</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {types.map((at) => (
                <tr key={at.id} className="border-b last:border-0">
                  <td className="px-4 py-2 font-mono text-xs">{at.id}</td>
                  <td className="px-4 py-2 font-medium">{at.label}</td>
                  <td className="max-w-xs truncate px-4 py-2 font-mono text-xs text-muted-foreground">{at.filename}</td>
                  <td className="max-w-xs truncate px-4 py-2 font-mono text-xs text-muted-foreground">{at.target_path}</td>
                  <td className="px-4 py-2">
                    <Badge variant={at.mode === 'merge' ? 'outline' : 'secondary'}>
                      {at.mode === 'merge'
                        ? t('admin.agentTypes.modeMerge')
                        : t('admin.agentTypes.modeReplace')}
                    </Badge>
                  </td>
                  <td className="px-4 py-2">
                    <Badge variant={at.enabled ? 'default' : 'secondary'}>
                      {at.enabled ? t('admin.agentTypes.enabled') : t('admin.agentTypes.disabled')}
                    </Badge>
                  </td>
                  <td className="flex items-center justify-end gap-1 px-4 py-2 text-right">
                    <Button size="sm" variant="ghost" onClick={() => setEditTarget(at)}>
                      {t('common.edit')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => setDeleteTarget(at)}
                    >
                      {t('common.delete')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {createOpen && (
        <AgentTypeFormDialog agentType={null} open onClose={() => setCreateOpen(false)} />
      )}
      {editTarget && (
        <AgentTypeFormDialog
          key={editTarget.id}
          agentType={editTarget}
          open
          onClose={() => setEditTarget(null)}
        />
      )}
      <DeleteAgentTypeDialog agentType={deleteTarget} onClose={() => setDeleteTarget(null)} />
    </div>
  )
}
