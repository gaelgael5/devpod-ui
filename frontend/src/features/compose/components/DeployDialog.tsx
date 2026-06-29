import { useState } from 'react'
import { useTranslation } from 'react-i18next'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import ParametersForm from './ParametersForm'
import { useNodes, useCreateDeployment } from '../hooks/useCompose'
import type { ComposeTemplate, PortConflictDetail } from '../api/types'

interface DeployDialogProps {
  template: ComposeTemplate
  open: boolean
  onOpenChange: (open: boolean) => void
}

function parsePortConflict(e: unknown): PortConflictDetail | null {
  if (!(e instanceof Error)) return null
  try {
    const parsed = JSON.parse(e.message) as Record<string, unknown>
    // FastAPI wraps detail in {detail: ...}; when detail is an object the raw text keeps the wrapper
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

function initEnvValues(parameters: ComposeTemplate['parameters']): Record<string, string> {
  return Object.fromEntries(parameters.map((p) => [p.key, p.default ?? '']))
}

export default function DeployDialog({ template, open, onOpenChange }: DeployDialogProps) {
  const { t } = useTranslation()
  const { data: nodes = [] } = useNodes()
  const createDeployment = useCreateDeployment()

  const [nodeId, setNodeId] = useState('')
  const [name, setName] = useState('')
  const [envValues, setEnvValues] = useState<Record<string, string>>(() =>
    initEnvValues(template.parameters),
  )
  const [serverError, setServerError] = useState<string | null>(null)

  function handleClose() {
    setNodeId('')
    setName('')
    setEnvValues(initEnvValues(template.parameters))
    setServerError(null)
    createDeployment.reset()
    onOpenChange(false)
  }

  async function handleSubmit() {
    setServerError(null)
    try {
      await createDeployment.mutateAsync({
        template_id: template.id,
        node_id: nodeId,
        name: name.trim(),
        env_values: envValues,
      })
      onOpenChange(false)
    } catch (e) {
      const detail = parsePortConflict(e)
      if (detail?.error === 'port_conflict') {
        const ports = detail.conflicts.join(', ')
        setServerError(
          t('compose.deployDialog.portConflict', {
            ports,
            suggestion: detail.suggestion ?? '',
          }),
        )
        // Pre-fill the first port param with the suggestion
        if (detail.suggestion !== null) {
          const portParam = template.parameters.find((p) => p.type === 'port')
          if (portParam) {
            setEnvValues((prev) => ({
              ...prev,
              [portParam.key]: String(detail.suggestion),
            }))
          }
        }
      } else {
        setServerError((e as Error).message)
      }
    }
  }

  const canSubmit = Boolean(nodeId) && Boolean(name.trim()) && !createDeployment.isPending

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('compose.deployDialog.title', { name: template.name })}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="deploy-name">{t('compose.form.name')}</Label>
            <Input
              id="deploy-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-deployment"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="deploy-node">{t('compose.form.node')}</Label>
            <Select value={nodeId} onValueChange={setNodeId}>
              <SelectTrigger id="deploy-node">
                <SelectValue placeholder="…" />
              </SelectTrigger>
              <SelectContent>
                {[...nodes]
                  .sort((a, b) => {
                    const wa = a.workspace_name ?? ''
                    const wb = b.workspace_name ?? ''
                    return wa !== wb ? wa.localeCompare(wb) : a.name.localeCompare(b.name)
                  })
                  .map((n) => (
                    <SelectItem key={n.node_id} value={n.node_id}>
                      {n.usage === 'tests' && n.workspace_name
                        ? `${n.workspace_name} / ${n.alias || n.name}`
                        : n.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          {template.parameters.length > 0 && (
            <ParametersForm
              parameters={template.parameters}
              values={envValues}
              onChange={(key, value) => setEnvValues((prev) => ({ ...prev, [key]: value }))}
            />
          )}
          {serverError && <p className="text-sm text-destructive">{serverError}</p>}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={handleClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void handleSubmit()} disabled={!canSubmit}>
            {createDeployment.isPending ? '…' : t('compose.deployDialog.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
