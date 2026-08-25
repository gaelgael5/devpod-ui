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
  type ScriptArg, type ScriptSpec, type ScriptSubArg, type ScriptArgOrSub,
} from './useProxmoxScript'
import { apiFetch } from '@/shared/api/client'
import type { HostConfig } from './useHosts'
import { useMachineProfiles, type MachineProfile } from './useMachineProfiles'

// ─── Types ────────────────────────────────────────────────────────────────────

type Step =
  | { kind: 'select' }
  | { kind: 'profils'; node: HypervisorConfig }
  | {
      kind: 'params'
      node: HypervisorConfig
      /** Valeurs deja decidees (profil + defauts de la spec). */
      preset: Record<string, string>
      /** Restreint le formulaire a ces args. Absent = formulaire complet. */
      onlyArgs?: ScriptArg[]
    }
  | { kind: 'log'; node: HypervisorConfig; args: Record<string, string> }

// ─── Helpers ──────────────────────────────────────────────────────────────────

function argLabel(arg: ScriptArg | ScriptSubArg): string {
  return i18n.language.startsWith('fr') ? arg.label_fr : arg.label_en
}

function argDescription(arg: ScriptArg): string | undefined {
  return i18n.language.startsWith('fr') ? arg.description_fr : arg.description_en
}

/**
 * Args obligatoires qu'aucune valeur ne renseigne. Le profil fige le reste :
 * les reafficher n'apporterait rien, et allongerait un ecran ou seul ce qui
 * manque demande une decision.
 */
function argsManquants(args: ScriptArgOrSub[], values: Record<string, string>): ScriptArg[] {
  return flattenArgs(args).filter(a => a.required && !values[a.arg])
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
  if (json.type === 'docker-tls') {
    return {
      name,
      type: 'docker-tls',
      docker_host: String(json.docker_host ?? `tcp://${address}:2376`),
      address: '',
      default: false,
      vmid: resolvedVmid,
      proxmox_node: resolvedProxmoxNode,
    }
  }
  return {
    name,
    type: 'ssh',
    docker_host: '',
    address: `${sshUser}@${address}`,
    default: false,
    vmid: resolvedVmid,
    proxmox_node: resolvedProxmoxNode,
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

// ─── Step 2 : arbre des profils de machine ────────────────────────────────────

/** Ordre d'affichage des groupes. `portail` n'y figure pas : le portail ne se
 *  cree pas depuis un profil. */
const GROUPES = ['workspaces', 'test', 'ressources', 'autres'] as const

function StepProfils({
  node,
  onChoose,
  onBack,
}: {
  node: HypervisorConfig
  /** `null` = creation libre, sans profil. */
  onChoose: (profil: MachineProfile | null, spec: ScriptSpec) => void
  onBack: () => void
}) {
  const { t } = useTranslation()
  const { data: spec, isLoading: specLoading } = useScriptSpec(node.name)
  const { data: profils = [], isLoading } = useMachineProfiles()

  // Un profil est type par la spec du script de SON hyperviseur : en proposer
  // un d'un autre type produirait des args que le script ne connait pas.
  const compatibles = profils.filter(p => p.hypervisor_type === node.hypervisor_type)

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t('admin.generate.profileTitle')} — {node.name}</DialogTitle>
      </DialogHeader>

      <div className="flex flex-col gap-3 py-1">
        {(isLoading || specLoading) && <p className="text-sm text-muted-foreground">…</p>}

        {!isLoading && GROUPES.map(groupe => {
          const duGroupe = compatibles.filter(p => p.machine_type === groupe)
          return (
            <div key={groupe}>
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                {t(`admin.machineProfiles.type.${groupe}`)}
              </p>
              {duGroupe.length === 0 ? (
                <p className="pl-3 text-xs text-muted-foreground/70">
                  {t('admin.generate.noProfileInGroup')}
                </p>
              ) : (
                <div className="flex flex-col gap-1 pl-3">
                  {duGroupe.map(p => (
                    <button
                      key={p.slug}
                      type="button"
                      disabled={!spec}
                      onClick={() => spec && onChoose(p, spec)}
                      className="flex items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-muted disabled:opacity-50"
                    >
                      <span className="font-medium">{p.label}</span>
                      <span className="font-mono text-xs text-muted-foreground">{p.slug}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {/* Sans profil, on retombe sur la saisie complete : supprimer cette
            porte de sortie rendrait l'hyperviseur inutilisable tant qu'aucun
            profil n'existe pour son type. */}
        <button
          type="button"
          disabled={!spec}
          onClick={() => spec && onChoose(null, spec)}
          className="mt-1 rounded-md border border-dashed px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
        >
          {t('admin.generate.noProfile')}
        </button>
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onBack}>{t('admin.generate.back')}</Button>
      </DialogFooter>
    </>
  )
}

// ─── Step 3 : formulaire de paramètres ────────────────────────────────────────

function StepParams({
  node,
  preset,
  onlyArgs,
  onExecute,
  onBack,
}: {
  node: HypervisorConfig
  preset: Record<string, string>
  onlyArgs?: ScriptArg[]
  onExecute: (args: Record<string, string>) => void
  onBack: () => void
}) {
  const { t } = useTranslation()
  const { data: spec, isLoading, isError, error } = useScriptSpec(node.name)

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
        <StepParamsForm
          node={node}
          spec={spec}
          preset={preset}
          onlyArgs={onlyArgs}
          onExecute={onExecute}
          onBack={onBack}
        />
      )}

      {!spec && !isLoading && (
        <DialogFooter>
          <Button variant="outline" onClick={onBack}>{t('admin.generate.back')}</Button>
        </DialogFooter>
      )}
    </>
  )
}

// Formulaire monté une fois le spec chargé : `values` est initialisé au montage
// via useState (pas d'hydratation par effet — la saisie n'est plus écrasée par
// un refetch du spec).
function StepParamsForm({
  node,
  spec,
  preset,
  onlyArgs,
  onExecute,
  onBack,
}: {
  node: HypervisorConfig
  spec: ScriptSpec
  preset: Record<string, string>
  /** Restreint le rendu a ces args ; les autres partent tels quels dans preset. */
  onlyArgs?: ScriptArg[]
  onExecute: (args: Record<string, string>) => void
  onBack: () => void
}) {
  const { t } = useTranslation()
  const [values, setValues] = useState<Record<string, string>>(() => ({
    ...initValues(spec.args),
    ...preset,
  }))
  const [argErrors, setArgErrors] = useState<Record<string, string>>({})
  const [validatingArgs, setValidatingArgs] = useState<Set<string>>(new Set())

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
      const argsWithTest = flattenArgs(spec.args).filter(a => a.test_script)
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
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      {onlyArgs !== undefined && onlyArgs.length > 0 && (
        <p className="text-xs text-muted-foreground">{t('admin.generate.missingHint')}</p>
      )}
      {(onlyArgs ?? spec.args).map((arg: ScriptArgOrSub, i: number) =>
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
  onAddHost: (config: HostConfig, ciPassword?: string) => void
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
  const hostConfig = result?.status === 'ok'
    ? mapToHostConfig(result, args.NEW_VMID, node.name)
    : null

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
        <div className="flex flex-col gap-3">
          <div className="text-sm">
            {hostConfig ? (
              <p className="text-green-600">{t('admin.generate.resultFound')}</p>
            ) : (
              <p className="text-destructive">{t('admin.generate.resultMissing')}</p>
            )}
          </div>

        </div>
      )}

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>{t('workspaces.confirm.cancel')}</Button>
        {done && !hostConfig && (
          <Button variant="outline" onClick={handleRetry}>{t('workspaces.actions.retry')}</Button>
        )}
        {hostConfig && (
          <Button onClick={() => onAddHost(hostConfig, result?.ci_password as string | undefined)}>
            {t('admin.generate.addGenerated')}
          </Button>
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
  onGenerated: (config: HostConfig, ciPassword?: string) => void
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
            onSelect={node => setStep({ kind: 'profils', node })}
            onClose={onClose}
          />
        )}
        {step.kind === 'profils' && (
          <StepProfils
            node={step.node}
            onChoose={(profil, spec) => {
              const node = (step as { node: HypervisorConfig }).node
              if (profil === null) {
                setStep({ kind: 'params', node, preset: initValues(spec.args) })
                return
              }
              // Le profil fige les parametres. Ne restent a saisir que les args
              // obligatoires qu'il ne renseigne pas ; s'il n'en manque aucun,
              // rien n'est demande et la creation part directement.
              const values = { ...initValues(spec.args), ...profil.params }
              const manquants = argsManquants(spec.args, values)
              if (manquants.length === 0) {
                setStep({ kind: 'log', node, args: values })
              } else {
                setStep({ kind: 'params', node, preset: values, onlyArgs: manquants })
              }
            }}
            onBack={() => setStep({ kind: 'select' })}
          />
        )}
        {step.kind === 'params' && (
          <StepParams
            node={step.node}
            preset={step.preset}
            onlyArgs={step.onlyArgs}
            onExecute={args => setStep({ kind: 'log', node: step.node, args })}
            onBack={() => setStep({ kind: 'profils', node: step.node })}
          />
        )}
        {step.kind === 'log' && (
          <StepLog
            node={step.node}
            args={step.args}
            onAddHost={(config, ciPassword) => { onGenerated(config, ciPassword); onClose() }}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
