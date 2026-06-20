import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '@/i18n'
import { ChevronDown, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useAdminProxmox, type HypervisorConfig } from './useAdminProxmox'
import {
  useScriptSpec, useExecuteScript, extractLastJson, flattenArgs,
  type ScriptArg, type ScriptSubArg, type ScriptArgOrSub,
} from './useProxmoxScript'
import { apiFetch } from '@/shared/api/client'
import type { HostConfig } from './useHosts'

// ─── Types ────────────────────────────────────────────────────────────────────

type Step =
  | { kind: 'select' }
  | { kind: 'params'; node: HypervisorConfig }
  | { kind: 'log'; node: HypervisorConfig; args: Record<string, string> }

// ─── Helpers ──────────────────────────────────────────────────────────────────

function argLabel(arg: ScriptArg | ScriptSubArg): string {
  return i18n.language.startsWith('fr') ? arg.label_fr : arg.label_en
}

function argDescription(arg: ScriptArg): string | undefined {
  return i18n.language.startsWith('fr') ? arg.description_fr : arg.description_en
}

function initValues(args: ScriptArgOrSub[]): Record<string, string> {
  return Object.fromEntries(
    flattenArgs(args).map(a => {
      if (a.default !== undefined) return [a.arg, String(a.default)]
      if (a.type === 'select' && a.options && a.options.length > 0) return [a.arg, a.options[0].value]
      return [a.arg, '']
    })
  )
}

function mapToHostConfig(
  json: Record<string, unknown>,
  vmid?: string,
  proxmoxNode?: string,
): HostConfig {
  const name = String(json.name ?? '')
  const address = String(json.address ?? '')
  const sshUser = String(json.ssh_user ?? 'debian')
  const resolvedVmid = String(json.vmid ?? vmid ?? '')
  const resolvedProxmoxNode = String(json.proxmox_node ?? proxmoxNode ?? '')
  const resolvedCiPassword = json.ci_password ? String(json.ci_password) : undefined
  if (json.type === 'docker-tls') {
    return {
      name,
      type: 'docker-tls',
      docker_host: String(json.docker_host ?? `tcp://${address}:2376`),
      address: '',
      key_path: String(json.key_path ?? '/data/certs/portal'),
      default: false,
      vmid: resolvedVmid,
      proxmox_node: resolvedProxmoxNode,
      ci_password: resolvedCiPassword,
    }
  }
  return {
    name,
    type: 'ssh',
    docker_host: '',
    address: `${sshUser}@${address}`,
    key_path: '',
    default: false,
    vmid: resolvedVmid,
    proxmox_node: resolvedProxmoxNode,
    ci_password: resolvedCiPassword,
  }
}

// ─── Step 1 : sélection du nœud ───────────────────────────────────────────────

function StepSelect({
  onSelect,
  onClose,
}: {
  onSelect: (node: HypervisorConfig) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { nodesQuery } = useAdminProxmox()
  const nodes = (nodesQuery.data ?? [] as HypervisorConfig[]).filter((n: HypervisorConfig) => n.hypervisor_type)

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
        {nodes.map((n: HypervisorConfig) => (
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
  node: HypervisorConfig
  onExecute: (args: Record<string, string>) => void
  onBack: () => void
}) {
  const { t } = useTranslation()
  const { data: spec, isLoading, isError, error } = useScriptSpec(node.name)
  const [values, setValues] = useState<Record<string, string>>({})
  const [argErrors, setArgErrors] = useState<Record<string, string>>({})
  const [validatingArgs, setValidatingArgs] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (spec) setValues(initValues(spec.args))
  }, [spec])

  function set(key: string, value: string) {
    setValues(v => ({ ...v, [key]: value }))
    // Efface l'erreur dès que l'utilisateur modifie la valeur
    if (argErrors[key]) setArgErrors(e => ({ ...e, [key]: '' }))
  }

  const validateArgApi = useCallback(async (
    arg: ScriptArg,
    currentValues: Record<string, string>,
  ): Promise<boolean> => {
    if (!arg.test_script) return true
    setValidatingArgs(s => new Set(s).add(arg.arg))
    try {
      const res = await apiFetch(`/admin/hypervisors/${node.name}/validate-arg`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arg: arg.arg, args: currentValues }),
      })
      if (!res.ok) return true  // erreur réseau → ne bloque pas
      const data = await res.json() as { valid: boolean; message: string | null }
      setArgErrors(e => ({ ...e, [arg.arg]: data.valid ? '' : (data.message ?? 'Valeur invalide') }))
      return data.valid
    } catch {
      return true  // erreur SSH → ne bloque pas
    } finally {
      setValidatingArgs(s => { const n = new Set(s); n.delete(arg.arg); return n })
    }
  }, [node.name])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    void (async () => {
      const argsWithTest = flattenArgs(spec!.args).filter(a => a.test_script)
      if (argsWithTest.length > 0) {
        const results = await Promise.all(argsWithTest.map(a => validateArgApi(a, values)))
        if (results.some(r => !r)) return
      }
      onExecute(values)
    })()
  }

  const isValidating = validatingArgs.size > 0
  const hasErrors = Object.values(argErrors).some(e => !!e)

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
          {spec.args.map((arg: ScriptArgOrSub, i: number) =>
            arg.type === 'sub'
              ? (
                <SubGroup
                  key={i}
                  sub={arg}
                  values={values}
                  onChange={set}
                  onBlurArg={a => { void validateArgApi(a, values) }}
                  argErrors={argErrors}
                  validatingArgs={validatingArgs}
                />
              )
              : (
                <ArgField
                  key={arg.arg}
                  arg={arg}
                  value={values[arg.arg] ?? ''}
                  onChange={v => set(arg.arg, v)}
                  onBlur={arg.test_script ? () => { void validateArgApi(arg, values) } : undefined}
                  validationError={argErrors[arg.arg]}
                  validating={validatingArgs.has(arg.arg)}
                />
              )
          )}
          <DialogFooter className="mt-2">
            <Button type="button" variant="outline" onClick={onBack}>{t('admin.generate.back')}</Button>
            <Button type="submit" disabled={isValidating || hasErrors}>
              {isValidating ? <Loader2 className="h-4 w-4 animate-spin" /> : t('admin.generate.execute')}
            </Button>
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

function SubGroup({
  sub,
  values,
  onChange,
  onBlurArg,
  argErrors,
  validatingArgs,
}: {
  sub: ScriptSubArg
  values: Record<string, string>
  onChange: (key: string, value: string) => void
  onBlurArg: (arg: ScriptArg) => void
  argErrors: Record<string, string>
  validatingArgs: Set<string>
}) {
  const [open, setOpen] = useState(sub.expanded ?? false)

  return (
    <div className="rounded-md border">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-muted/50 transition-colors rounded-md"
      >
        <span>{argLabel(sub)}</span>
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="flex flex-col gap-3 px-3 pb-3">
          {sub.args.map(arg => (
            <ArgField
              key={arg.arg}
              arg={arg}
              value={values[arg.arg] ?? ''}
              onChange={v => onChange(arg.arg, v)}
              onBlur={arg.test_script ? () => onBlurArg(arg) : undefined}
              validationError={argErrors[arg.arg]}
              validating={validatingArgs.has(arg.arg)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ArgLabel({
  label, required, validating,
}: {
  label: string
  required?: boolean
  validating?: boolean
}) {
  return (
    <Label className="flex items-center gap-1.5">
      {label}
      {required && <span className="text-destructive">*</span>}
      {validating && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
    </Label>
  )
}

function ArgField({
  arg,
  value,
  onChange,
  onBlur,
  validationError,
  validating,
}: {
  arg: ScriptArg
  value: string
  onChange: (v: string) => void
  onBlur?: () => void
  validationError?: string
  validating?: boolean
}) {
  const label = argLabel(arg)
  const description = argDescription(arg)

  function wrap(input: ReactNode, extra?: ReactNode) {
    return (
      <div className="flex flex-col gap-1.5">
        <ArgLabel label={label} required={arg.required} validating={validating} />
        {description && <p className="text-xs text-muted-foreground -mt-0.5">{description}</p>}
        {input}
        {extra}
        {validationError && <p className="text-xs text-destructive">{validationError}</p>}
      </div>
    )
  }

  if (arg.options && arg.options.length > 0) {
    return wrap(
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent>
          {arg.options.map(o => (
            <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>,
      arg._option_script_error && (
        <p className="text-xs text-destructive">{arg._option_script_error}</p>
      ),
    )
  }

  if (arg.type === 'integer') {
    return wrap(
      <Input
        type="number"
        value={value}
        onChange={e => onChange(e.target.value)}
        onBlur={onBlur}
        min={arg.min}
        max={arg.max}
        required={arg.required}
      />,
    )
  }

  return wrap(
    <Input
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      onBlur={onBlur}
      pattern={arg.pattern}
      required={arg.required}
    />,
  )
}

// ─── Step 3 : logs d'exécution ────────────────────────────────────────────────

function StepLog({
  node,
  args,
  onAddHost,
  onClose,
}: {
  node: HypervisorConfig
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
  const hostConfig = result?.status === 'ok' ? mapToHostConfig(result, args.NEW_VMID, node.name) : null

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
