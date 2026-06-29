import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import ParametersForm from './ParametersForm'
import { useTemplates, useCreateDeployment } from '../hooks/useCompose'
import type { ComposeTemplate, PortConflictDetail } from '../api/types'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** node_id de la machine de test cible (= TestHost.name) */
  nodeId: string
  /** Label affiché dans le dialog (= TestHost.alias) */
  nodeLabel: string
}

function parsePortConflict(e: unknown): PortConflictDetail | null {
  if (!(e instanceof Error)) return null
  try {
    const parsed = JSON.parse(e.message) as Record<string, unknown>
    const inner =
      typeof parsed.detail === 'object' && parsed.detail !== null
        ? (parsed.detail as Record<string, unknown>)
        : parsed
    if (inner.error !== 'port_conflict') return null
    return {
      error: 'port_conflict',
      conflicts: Array.isArray(inner.conflicts) ? (inner.conflicts as number[]) : [],
      suggestion: typeof inner.suggestion === 'number' ? inner.suggestion : null,
    }
  } catch {
    return null
  }
}

/** Étape 1 : sélection du template */
function TemplatePicker({
  onPick,
}: {
  onPick: (tpl: ComposeTemplate) => void
}) {
  const { t } = useTranslation()
  const { data: templates = [], isLoading } = useTemplates()

  if (isLoading) return <p className="text-sm text-muted-foreground">…</p>
  if (templates.length === 0)
    return <p className="text-sm text-muted-foreground">{t('compose.launch.noTemplates')}</p>

  return (
    <div className="flex flex-col gap-2 max-h-72 overflow-y-auto pr-1">
      {templates.map((tpl) => (
        <button
          key={tpl.id}
          className="flex items-start gap-3 rounded-md border bg-card p-3 text-left hover:bg-accent transition-colors"
          onClick={() => onPick(tpl)}
        >
          <div className="flex-1 min-w-0">
            <div className="font-medium text-sm">{tpl.name}</div>
            {tpl.description && (
              <div className="text-xs text-muted-foreground line-clamp-1">{tpl.description}</div>
            )}
            {tpl.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {tpl.tags.map((tag) => (
                  <Badge key={tag} variant="secondary" className="text-xs px-1 py-0">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}
          </div>
          <span className="text-xs text-muted-foreground font-mono shrink-0">v{tpl.version}</span>
        </button>
      ))}
    </div>
  )
}

/** Étape 2 : paramètres + nom du déploiement */
function DeployForm({
  template,
  nodeId,
  nodeLabel,
  onBack,
  onSuccess,
}: {
  template: ComposeTemplate
  nodeId: string
  nodeLabel: string
  onBack: () => void
  onSuccess: () => void
}) {
  const { t } = useTranslation()
  const createDeployment = useCreateDeployment()
  const [name, setName] = useState('')
  const [envValues, setEnvValues] = useState<Record<string, string>>(
    () => Object.fromEntries(template.parameters.map((p) => [p.key, p.default ?? ''])),
  )
  const [serverError, setServerError] = useState<string | null>(null)

  async function handleSubmit() {
    setServerError(null)
    try {
      await createDeployment.mutateAsync({
        template_id: template.id,
        node_id: nodeId,
        name: name.trim(),
        env_values: envValues,
      })
      onSuccess()
    } catch (e) {
      const conflict = parsePortConflict(e)
      if (conflict?.error === 'port_conflict') {
        const ports = conflict.conflicts.join(', ')
        setServerError(t('compose.deployDialog.portConflict', { ports, suggestion: conflict.suggestion ?? '' }))
        if (conflict.suggestion !== null) {
          const portParam = template.parameters.find((p) => p.type === 'port')
          if (portParam)
            setEnvValues((prev) => ({ ...prev, [portParam.key]: String(conflict.suggestion) }))
        }
      } else {
        setServerError((e as Error).message)
      }
    }
  }

  const canSubmit = Boolean(name.trim()) && !createDeployment.isPending

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md bg-muted px-3 py-1.5 text-xs text-muted-foreground">
        {t('compose.launch.targetNode')}: <span className="font-medium text-foreground">{nodeLabel}</span>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="svc-name">{t('compose.form.name')}</Label>
        <Input
          id="svc-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-service"
          autoFocus
        />
      </div>

      {template.parameters.filter((p) => p.type !== 'port').length > 0 && (
        <ParametersForm
          parameters={template.parameters.filter((p) => p.type !== 'port')}
          values={envValues}
          onChange={(key, value) => setEnvValues((prev) => ({ ...prev, [key]: value }))}
        />
      )}

      {serverError && <p className="text-sm text-destructive">{serverError}</p>}

      <DialogFooter>
        <Button variant="ghost" onClick={onBack}>
          {t('compose.launch.back')}
        </Button>
        <Button onClick={() => void handleSubmit()} disabled={!canSubmit}>
          {createDeployment.isPending ? '…' : t('compose.launch.start')}
        </Button>
      </DialogFooter>
    </div>
  )
}

export default function ServiceLaunchDialog({ open, onOpenChange, nodeId, nodeLabel }: Props) {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<ComposeTemplate | null>(null)

  function handleClose() {
    setSelected(null)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {selected
              ? t('compose.launch.titleDeploy', { name: selected.name })
              : t('compose.launch.titlePick')}
          </DialogTitle>
        </DialogHeader>

        {!selected ? (
          <>
            <TemplatePicker onPick={setSelected} />
            <DialogFooter>
              <Button variant="ghost" onClick={handleClose}>{t('common.cancel')}</Button>
            </DialogFooter>
          </>
        ) : (
          <DeployForm
            template={selected}
            nodeId={nodeId}
            nodeLabel={nodeLabel}
            onBack={() => setSelected(null)}
            onSuccess={handleClose}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
