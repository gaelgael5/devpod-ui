import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
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
import { apiFetch } from '@/shared/api/client'
import ParametersForm from './ParametersForm'
import { useNodes } from '../hooks/useCompose'
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
  const qc = useQueryClient()

  const [nodeId, setNodeId] = useState('')
  const [name, setName] = useState('')
  const [envValues, setEnvValues] = useState<Record<string, string>>(() =>
    initEnvValues(template.parameters),
  )
  const [serverError, setServerError] = useState<string | null>(null)
  const [logs, setLogs] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamDone, setStreamDone] = useState(false)
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  function handleClose() {
    if (streaming) return
    setNodeId('')
    setName('')
    setEnvValues(initEnvValues(template.parameters))
    setServerError(null)
    setLogs('')
    setStreaming(false)
    setStreamDone(false)
    onOpenChange(false)
  }

  const handleSubmit = useCallback(async () => {
    setServerError(null)
    setLogs('')
    setStreamDone(false)

    let res: Response
    try {
      res = await apiFetch('/api/compose/deployments/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_id: template.id,
          node_id: nodeId,
          name: name.trim(),
          env_values: envValues,
        }),
      })
    } catch (e) {
      setServerError(e instanceof Error ? e.message : String(e))
      return
    }

    if (!res.ok) {
      const text = await res.text().catch(() => '')
      const detail = parsePortConflict(new Error(text))
      if (detail?.error === 'port_conflict') {
        const ports = detail.conflicts.join(', ')
        setServerError(
          t('compose.deployDialog.portConflict', {
            ports,
            suggestion: detail.suggestion ?? '',
          }),
        )
        if (detail.suggestion !== null) {
          const portParam = template.parameters.find((p) => p.type === 'port')
          if (portParam) {
            setEnvValues((prev) => ({ ...prev, [portParam.key]: String(detail.suggestion) }))
          }
        }
      } else {
        setServerError(text || `HTTP ${res.status}`)
      }
      return
    }

    setStreaming(true)
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let accum = ''
    let success = false

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        accum += decoder.decode(value, { stream: true })
        setLogs(accum)
      }
    } finally {
      setStreaming(false)
      setStreamDone(true)
    }

    const lastLine = accum.trimEnd().split('\n').at(-1) ?? ''
    if (lastLine.startsWith('__RESULT__:')) {
      success = true
      void qc.invalidateQueries({ queryKey: ['compose', 'deployments'] })
      onOpenChange(false)
    } else if (lastLine.startsWith('__ERROR__:')) {
      const msg = lastLine.slice('__ERROR__:'.length)
      setServerError(msg || t('compose.deployDialog.deployFailed'))
    }
    if (!success && !lastLine.startsWith('__ERROR__:')) {
      setServerError(t('compose.deployDialog.deployFailed'))
    }
  }, [template, nodeId, name, envValues, qc, onOpenChange, t])

  const missingRequired = template.parameters.some(
    (p) => p.required && !envValues[p.key]?.trim(),
  )
  const canSubmit =
    Boolean(nodeId) && Boolean(name.trim()) && !missingRequired && !streaming

  const showLogs = streaming || streamDone

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && !streaming) handleClose() }}>
      <DialogContent className="max-w-[45rem]">
        <DialogHeader>
          <DialogTitle>{t('compose.deployDialog.title', { name: template.name })}</DialogTitle>
        </DialogHeader>

        {!showLogs ? (
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
        ) : (
          <div className="flex flex-col gap-2">
            <pre
              ref={logRef}
              className="max-h-[55vh] overflow-auto whitespace-pre-wrap rounded bg-black/90 p-3 text-xs text-green-200"
            >
              {logs || '…'}
            </pre>
            {streamDone && serverError && (
              <p className="text-sm text-destructive">{serverError}</p>
            )}
          </div>
        )}

        <DialogFooter>
          {!showLogs ? (
            <>
              <Button variant="ghost" onClick={handleClose}>
                {t('common.cancel')}
              </Button>
              <Button onClick={() => void handleSubmit()} disabled={!canSubmit}>
                {t('compose.deployDialog.submit')}
              </Button>
            </>
          ) : (
            <Button onClick={handleClose} disabled={streaming}>
              {streaming
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : t('common.close')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
