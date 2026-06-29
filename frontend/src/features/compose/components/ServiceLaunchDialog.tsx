import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
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
import { apiFetch } from '@/shared/api/client'
import ParametersForm from './ParametersForm'
import { useTemplates } from '../hooks/useCompose'
import type { ComposeTemplate, PortConflictDetail } from '../api/types'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** node_id de la machine de test cible (= TestHost.name) */
  nodeId: string
  /** Label affiché dans le dialog (= TestHost.alias) */
  nodeLabel: string
}

function parsePortConflict(text: string): PortConflictDetail | null {
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>
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
function TemplatePicker({ onPick }: { onPick: (tpl: ComposeTemplate) => void }) {
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

/** Étape 2 : paramètres + streaming */
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
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [envValues, setEnvValues] = useState<Record<string, string>>(
    () => Object.fromEntries(template.parameters.map((p) => [p.key, p.default ?? ''])),
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
      const conflict = parsePortConflict(text)
      if (conflict?.error === 'port_conflict') {
        const ports = conflict.conflicts.join(', ')
        setServerError(
          t('compose.deployDialog.portConflict', { ports, suggestion: conflict.suggestion ?? '' }),
        )
        if (conflict.suggestion !== null) {
          const portParam = template.parameters.find((p) => p.type === 'port')
          if (portParam)
            setEnvValues((prev) => ({ ...prev, [portParam.key]: String(conflict.suggestion) }))
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

    const lines = accum.trimEnd().split('\n')
    const lastLine = lines[lines.length - 1] ?? ''
    if (lastLine.startsWith('__RESULT__:')) {
      void qc.invalidateQueries({ queryKey: ['compose', 'deployments'] })
      onSuccess()
    } else {
      const msg = lastLine.startsWith('__ERROR__:')
        ? lastLine.slice('__ERROR__:'.length)
        : t('compose.deployDialog.deployFailed')
      setServerError(msg || t('compose.deployDialog.deployFailed'))
    }
  }, [template, nodeId, name, envValues, qc, onSuccess, t])

  const canSubmit = Boolean(name.trim()) && !streaming
  const showLogs = streaming || streamDone

  if (showLogs) {
    return (
      <div className="flex flex-col gap-3">
        <pre
          ref={logRef}
          className="max-h-[55vh] overflow-auto whitespace-pre-wrap rounded bg-black/90 p-3 text-xs text-green-200"
        >
          {logs || '…'}
        </pre>
        {streamDone && serverError && (
          <p className="text-sm text-destructive">{serverError}</p>
        )}
        <DialogFooter>
          <Button onClick={onBack} disabled={streaming}>
            {streaming
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : t('common.close')}
          </Button>
        </DialogFooter>
      </div>
    )
  }

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
          {t('compose.launch.start')}
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
      <DialogContent className="max-w-[45rem]">
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
