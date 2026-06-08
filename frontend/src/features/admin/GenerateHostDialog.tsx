import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '@/i18n'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useAdminProxmox, type ProxmoxNodeConfig } from './useAdminProxmox'
import {
  useScriptSpec, useExecuteScript, extractLastJson,
  type ScriptArg, type ScriptSpec,
} from './useProxmoxScript'
import type { HostConfig } from './useHosts'

// ─── Types ────────────────────────────────────────────────────────────────────

type Step =
  | { kind: 'select' }
  | { kind: 'params'; node: ProxmoxNodeConfig }
  | { kind: 'log'; node: ProxmoxNodeConfig; args: Record<string, string> }

// ─── Helpers ──────────────────────────────────────────────────────────────────

function argLabel(arg: ScriptArg): string {
  return i18n.language.startsWith('fr') ? arg.label_fr : arg.label_en
}

function initValues(args: ScriptArg[]): Record<string, string> {
  return Object.fromEntries(
    args.map(a => [a.arg, a.default !== undefined ? String(a.default) : ''])
  )
}

function mapToHostConfig(json: Record<string, unknown>): HostConfig {
  const name = String(json.name ?? '')
  const address = String(json.address ?? '')
  const sshUser = String(json.ssh_user ?? 'debian')
  if (json.type === 'docker-tls') {
    return {
      name,
      type: 'docker-tls',
      docker_host: String(json.docker_host ?? `tcp://${address}:2376`),
      address: '',
      key_path: String(json.key_path ?? '/data/certs/portal'),
      default: false,
    }
  }
  return {
    name,
    type: 'ssh',
    docker_host: '',
    address: `${sshUser}@${address}`,
    key_path: '',
    default: false,
  }
}

// ─── Step 1 : sélection du nœud ───────────────────────────────────────────────

function StepSelect({
  onSelect,
  onClose,
}: {
  onSelect: (node: ProxmoxNodeConfig) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { nodesQuery } = useAdminProxmox()
  const nodes = (nodesQuery.data ?? []).filter(n => n.script_url)

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t('admin.generate.selectNode')}</DialogTitle>
      </DialogHeader>
      <div className="flex flex-col gap-2 py-1">
        {nodesQuery.isLoading && <p className="text-sm text-muted-foreground">…</p>}
        {!nodesQuery.isLoading && nodes.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('admin.generate.noNodes')}</p>
        )}
        {nodes.map(n => (
          <button
            key={n.name}
            type="button"
            onClick={() => onSelect(n)}
            className="flex items-center justify-between rounded-md border px-4 py-3 text-left text-sm transition-colors hover:bg-muted"
          >
            <span className="font-medium">{n.name}</span>
            <span className="font-mono text-xs text-muted-foreground">{n.address}</span>
          </button>
        ))}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>{t('workspaces.confirm.cancel')}</Button>
      </DialogFooter>
    </>
  )
}

// ─── Step 2 : formulaire de paramètres ────────────────────────────────────────

function StepParams({
  node,
  onExecute,
  onBack,
}: {
  node: ProxmoxNodeConfig
  onExecute: (args: Record<string, string>) => void
  onBack: () => void
}) {
  const { t } = useTranslation()
  const { data: spec, isLoading, isError, error } = useScriptSpec(node.name)
  const [values, setValues] = useState<Record<string, string>>({})

  useEffect(() => {
    if (spec) setValues(initValues(spec.args))
  }, [spec])

  function set(key: string, value: string) {
    setValues(v => ({ ...v, [key]: value }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onExecute(values)
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t('admin.generate.paramTitle')} — {node.name}</DialogTitle>
      </DialogHeader>

      {isLoading && <p className="text-sm text-muted-foreground py-4 text-center">…</p>}
      {isError && (
        <p className="text-sm text-destructive py-2">
          {error instanceof Error ? error.message : t('errors.generic')}
        </p>
      )}

      {spec && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          {spec.args.map(arg => (
            <ArgField key={arg.arg} arg={arg} value={values[arg.arg] ?? ''} onChange={v => set(arg.arg, v)} />
          ))}
          <DialogFooter className="mt-2">
            <Button type="button" variant="outline" onClick={onBack}>{t('admin.generate.back')}</Button>
            <Button type="submit">{t('admin.generate.execute')}</Button>
          </DialogFooter>
        </form>
      )}

      {!spec && !isLoading && (
        <DialogFooter>
          <Button variant="outline" onClick={onBack}>{t('admin.generate.back')}</Button>
        </DialogFooter>
      )}
    </>
  )
}

function ArgField({
  arg,
  value,
  onChange,
}: {
  arg: ScriptArg
  value: string
  onChange: (v: string) => void
}) {
  const label = argLabel(arg)

  if (arg.type === 'select' && arg.options && arg.options.length > 0) {
    return (
      <div className="flex flex-col gap-1.5">
        <Label>{label}</Label>
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {arg.options.map(o => (
              <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  if (arg.type === 'integer') {
    return (
      <div className="flex flex-col gap-1.5">
        <Label>{label}</Label>
        <Input
          type="number"
          value={value}
          onChange={e => onChange(e.target.value)}
          min={arg.min}
          max={arg.max}
          required={arg.required}
        />
      </div>
    )
  }

  // string (default)
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <Input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        pattern={arg.pattern}
        required={arg.required}
      />
    </div>
  )
}

// ─── Step 3 : logs d'exécution ────────────────────────────────────────────────

function StepLog({
  node,
  args,
  onAddHost,
  onClose,
}: {
  node: ProxmoxNodeConfig
  args: Record<string, string>
  onAddHost: (config: HostConfig) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { logs, running, done, error, execute, reset } = useExecuteScript()
  const logRef = useRef<HTMLPreElement>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true
      void execute(node.name, args)
    }
  }, [execute, node.name, args])

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  const result = done && !error ? extractLastJson(logs) : null
  const hostConfig = result?.status === 'ok' ? mapToHostConfig(result) : null

  function handleRetry() {
    reset()
    startedRef.current = false
    void execute(node.name, args)
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {t('admin.generate.logTitle')} — {node.name}
          {running && <span className="ml-2 text-xs font-normal text-muted-foreground animate-pulse">{t('admin.generate.running')}</span>}
        </DialogTitle>
      </DialogHeader>

      <pre
        ref={logRef}
        className="h-72 overflow-y-auto rounded-md bg-muted p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap"
      >
        {logs || (running ? '…' : '')}
        {error && <span className="text-destructive">{'\n'}{error}</span>}
      </pre>

      {done && (
        <div className="text-sm">
          {hostConfig ? (
            <p className="text-green-600">{t('admin.generate.resultFound')}</p>
          ) : (
            <p className="text-destructive">{t('admin.generate.resultMissing')}</p>
          )}
        </div>
      )}

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>{t('workspaces.confirm.cancel')}</Button>
        {done && !hostConfig && (
          <Button variant="outline" onClick={handleRetry}>{t('workspaces.actions.retry')}</Button>
        )}
        {hostConfig && (
          <Button onClick={() => onAddHost(hostConfig)}>{t('admin.generate.addGenerated')}</Button>
        )}
      </DialogFooter>
    </>
  )
}

// ─── Composant principal ──────────────────────────────────────────────────────

export default function GenerateHostDialog({
  open,
  onClose,
  onGenerated,
}: {
  open: boolean
  onClose: () => void
  onGenerated: (config: HostConfig) => void
}) {
  const [step, setStep] = useState<Step>({ kind: 'select' })

  // Remise à zéro après fermeture (laisse l'animation se terminer)
  useEffect(() => {
    if (!open) {
      const t = setTimeout(() => setStep({ kind: 'select' }), 300)
      return () => clearTimeout(t)
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose() }}>
      <DialogContent className={step.kind === 'log' ? 'max-w-2xl' : undefined}>
        {step.kind === 'select' && (
          <StepSelect
            onSelect={node => setStep({ kind: 'params', node })}
            onClose={onClose}
          />
        )}
        {step.kind === 'params' && (
          <StepParams
            node={step.node}
            onExecute={args => setStep({ kind: 'log', node: step.node, args })}
            onBack={() => setStep({ kind: 'select' })}
          />
        )}
        {step.kind === 'log' && (
          <StepLog
            node={step.node}
            args={step.args}
            onAddHost={config => { onGenerated(config); onClose() }}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
