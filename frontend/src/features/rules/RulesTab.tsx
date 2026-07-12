import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ChevronDown, ChevronRight, Copy, FlaskConical, Link2, Pencil, Play, Plus, Trash2,
  Workflow, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useServices } from '@/features/services/api'
import {
  useCreateRule, useDeleteRule, useRuleEvents, useRules, useServiceTools,
  useTestRule, useTestServiceCall, useUpdateRule,
  type RuleOperator, type RuleTestResult, type RuleTraceEntry, type ServiceTool,
  type UserRule,
} from './api'

const OPERATORS: RuleOperator[] = ['eq', 'neq', 'contains', 'not_contains']

// État d'édition : les args restent du texte tant que le dialog est ouvert.
interface CallDraft {
  service_id: string
  tool: string
  args: string
  collapsed: boolean
}
interface ConditionDraft extends CallDraft {
  path: string
  operator: RuleOperator
  value: string
}

const emptyCall = (): CallDraft => ({ service_id: '', tool: '', args: '{}', collapsed: false })
const emptyCondition = (): ConditionDraft => ({
  ...emptyCall(), path: '', operator: 'not_contains', value: '',
})

function parseArgs(raw: string): Record<string, unknown> | null {
  const text = raw.trim() || '{}'
  try {
    const parsed: unknown = JSON.parse(text)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return parsed as Record<string, unknown>
  } catch {
    return null
  }
}

const draftFromCall = (c: { service_id: string | null; tool: string; args: Record<string, unknown> }): CallDraft => ({
  service_id: c.service_id ?? '',
  tool: c.tool,
  args: JSON.stringify(c.args),
  // Règle existante : blocs repliés par défaut, on déplie ce qu'on édite.
  collapsed: true,
})

/** Squelette de paramètres généré depuis l'inputSchema de l'outil choisi. */
function argsSkeleton(tool: ServiceTool | undefined): string {
  const props = (tool?.input_schema?.properties ?? {}) as Record<
    string,
    { type?: string; default?: unknown }
  >
  const out: Record<string, unknown> = {}
  for (const [key, p] of Object.entries(props)) {
    if (p?.default !== undefined) out[key] = p.default
    else if (p?.type === 'number' || p?.type === 'integer') out[key] = 0
    else if (p?.type === 'boolean') out[key] = false
    else if (p?.type === 'array') out[key] = []
    else if (p?.type === 'object') out[key] = {}
    else out[key] = ''
  }
  return JSON.stringify(out, null, 2)
}

// ── Champs service + méthode + args (partagés conditions/actions) ─────────────

function CallFields({
  idPrefix,
  draft,
  onChange,
  testWorkspace,
}: {
  idPrefix: string
  draft: CallDraft
  onChange: (patch: Partial<CallDraft>) => void
  testWorkspace: string
}) {
  const { t } = useTranslation()
  const { data: services = [] } = useServices()
  const { data: tools = [] } = useServiceTools(draft.service_id)
  const testCall = useTestServiceCall()
  const parsedArgs = parseArgs(draft.args)
  const argsInvalid = parsedArgs === null

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idPrefix}-service`}>{t('rules.service')}</Label>
          <Select
            value={draft.service_id}
            onValueChange={(v) => onChange({ service_id: v, tool: '' })}
          >
            <SelectTrigger id={`${idPrefix}-service`}>
              <SelectValue placeholder={t('rules.servicePlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {services.map((s) => (
                <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idPrefix}-tool`}>{t('rules.tool')}</Label>
          <Select
            value={draft.tool}
            onValueChange={(v) =>
              // Le squelette des paramètres suit la méthode choisie.
              onChange({ tool: v, args: argsSkeleton(tools.find((tl) => tl.name === v)) })
            }
            disabled={!draft.service_id}
          >
            <SelectTrigger id={`${idPrefix}-tool`}>
              <SelectValue placeholder={t('rules.toolPlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {tools.map((tl) => (
                <SelectItem key={tl.name} value={tl.name} title={tl.description}>
                  {tl.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-args`}>{t('rules.args')}</Label>
        <textarea
          id={`${idPrefix}-args`}
          value={draft.args}
          onChange={(e) => onChange({ args: e.target.value })}
          rows={3}
          spellCheck={false}
          placeholder='{"workspace_slug": "{workspace}"}'
          className="rounded-md border bg-transparent px-3 py-2 font-mono text-xs"
        />
        {argsInvalid && <p className="text-xs text-destructive">{t('rules.argsInvalid')}</p>}
        <p className="font-mono text-xs text-muted-foreground" title={t('rules.variablesTitle')}>
          {t('rules.variablesHint')}
        </p>
      </div>
      <div className="flex flex-col gap-2">
        {draft.args.includes('{workspace}') && !testWorkspace.trim() && (
          <p className="text-xs text-amber-600 dark:text-amber-500">
            {t('rules.testWorkspaceEmptyWarning')}
          </p>
        )}
        <Button
          size="sm"
          variant="outline"
          className="self-start"
          disabled={!draft.service_id || !draft.tool || argsInvalid || testCall.isPending}
          onClick={() =>
            testCall.mutate(
              {
                serviceId: draft.service_id,
                tool: draft.tool,
                args: parsedArgs ?? {},
                workspace: testWorkspace.trim() || null,
              },
              {
                onError: (e) =>
                  toast.error(e instanceof Error ? e.message : t('errors.generic')),
              },
            )
          }
        >
          <FlaskConical className="mr-1 h-3.5 w-3.5" />
          {testCall.isPending ? t('common.loading') : t('rules.testCall')}
        </Button>
        {testCall.data && !testCall.data.ok && (
          <p className="rounded-md border border-destructive p-2 font-mono text-xs">
            {testCall.data.error}
          </p>
        )}
        {testCall.data?.ok && (
          <div className="rounded-md border p-2">
            <p className="font-mono text-xs text-muted-foreground">
              {t('rules.testCallSent')} {JSON.stringify(testCall.data.args)}
            </p>
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted p-2 font-mono text-xs">
              {JSON.stringify(testCall.data.result, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Dialog création / édition ─────────────────────────────────────────────────

function RuleFormDialog({
  rule,
  open,
  onClose,
}: {
  rule?: UserRule
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { data: events = [] } = useRuleEvents()
  const { data: rules = [] } = useRules()
  const create = useCreateRule()
  const update = useUpdateRule()

  const [name, setName] = useState(rule?.name ?? '')
  const [eventType, setEventType] = useState(rule?.event_type ?? '')
  const [conditions, setConditions] = useState<ConditionDraft[]>(
    rule
      ? rule.conditions.map((c) => ({
          ...draftFromCall(c), path: c.path, operator: c.operator, value: c.value,
        }))
      : [emptyCondition()],
  )
  const [actions, setActions] = useState<CallDraft[]>(
    rule ? rule.actions.map(draftFromCall) : [emptyCall()],
  )
  const [nextRuleId, setNextRuleId] = useState(rule?.next_rule_id ?? '')
  // Valeur injectée dans {workspace} par les boutons « Tester » des appels MCP.
  const [testWorkspace, setTestWorkspace] = useState('')

  const isPending = create.isPending || update.isPending
  const chainCandidates = rules.filter((r) => r.id !== rule?.id)

  function close() {
    create.reset()
    update.reset()
    onClose()
  }

  function patchCondition(i: number, patch: Partial<ConditionDraft>) {
    setConditions((prev) => prev.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  }
  function patchAction(i: number, patch: Partial<CallDraft>) {
    setActions((prev) => prev.map((a, j) => (j === i ? { ...a, ...patch } : a)))
  }

  const callOk = (c: CallDraft) => !!c.service_id && !!c.tool && parseArgs(c.args) !== null
  const canSubmit =
    !!name.trim() && !!eventType && actions.length > 0 &&
    actions.every(callOk) && conditions.every(callOk)

  function submit() {
    const body = {
      name: name.trim(),
      enabled: rule?.enabled ?? true,
      event_type: eventType,
      conditions: conditions.map((c) => ({
        service_id: c.service_id,
        tool: c.tool,
        args: parseArgs(c.args) ?? {},
        path: c.path.trim(),
        operator: c.operator,
        value: c.value,
      })),
      actions: actions.map((a) => ({
        service_id: a.service_id,
        tool: a.tool,
        args: parseArgs(a.args) ?? {},
      })),
      next_rule_id: nextRuleId || null,
    }
    const onError = (e: unknown) =>
      toast.error(e instanceof Error ? e.message : t('errors.generic'))
    if (rule) {
      update.mutate({ id: rule.id, ...body }, { onSuccess: close, onError })
    } else {
      create.mutate(body, { onSuccess: close, onError })
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{rule ? t('rules.editTitle') : t('rules.createTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rule-name">{t('rules.name')}</Label>
              <Input
                id="rule-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('rules.namePlaceholder')}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rule-event">{t('rules.event')}</Label>
              <Select value={eventType} onValueChange={setEventType}>
                <SelectTrigger id="rule-event">
                  <SelectValue placeholder={t('rules.eventPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {events.map((ev) => (
                    <SelectItem key={ev} value={ev}>{ev}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rule-form-test-ws">{t('rules.formTestWorkspace')}</Label>
            <Input
              id="rule-form-test-ws"
              value={testWorkspace}
              onChange={(e) => setTestWorkspace(e.target.value)}
              placeholder="mon-projet"
            />
            <p className="text-xs text-muted-foreground">{t('rules.formTestWorkspaceHint')}</p>
          </div>

          <fieldset className="flex flex-col gap-3 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">{t('rules.conditionsLegend')}</legend>
            <p className="text-xs text-muted-foreground">{t('rules.conditionsHint')}</p>
            {conditions.map((cond, i) => (
              <div key={i} className="flex flex-col gap-2 rounded-md border bg-muted/30 p-3">
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                    aria-expanded={!cond.collapsed}
                    onClick={() => patchCondition(i, { collapsed: !cond.collapsed })}
                  >
                    {cond.collapsed ? (
                      <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                    )}
                    <span className="text-xs font-medium">
                      {t('rules.conditionN', { n: i + 1 })}
                    </span>
                    {cond.collapsed && (
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {cond.tool || '—'}
                      </span>
                    )}
                  </button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('rules.removeCondition')}
                    onClick={() => setConditions((prev) => prev.filter((_, j) => j !== i))}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
                {!cond.collapsed && (
                <>
                <CallFields
                  idPrefix={`rule-cond-${i}`}
                  draft={cond}
                  onChange={(patch) => patchCondition(i, patch)}
                  testWorkspace={testWorkspace}
                />
                <div className="grid grid-cols-3 gap-2">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`rule-cond-${i}-path`}>{t('rules.conditionPath')}</Label>
                    <Input
                      id={`rule-cond-${i}-path`}
                      value={cond.path}
                      onChange={(e) => patchCondition(i, { path: e.target.value })}
                      placeholder="slug"
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`rule-cond-${i}-op`}>{t('rules.conditionOperator')}</Label>
                    <Select
                      value={cond.operator}
                      onValueChange={(v) => patchCondition(i, { operator: v as RuleOperator })}
                    >
                      <SelectTrigger id={`rule-cond-${i}-op`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {OPERATORS.map((op) => (
                          <SelectItem key={op} value={op}>{t(`rules.op.${op}`)}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`rule-cond-${i}-value`}>{t('rules.conditionValue')}</Label>
                    <Input
                      id={`rule-cond-${i}-value`}
                      value={cond.value}
                      onChange={(e) => patchCondition(i, { value: e.target.value })}
                      placeholder="{workspace}"
                    />
                  </div>
                </div>
                </>
                )}
              </div>
            ))}
            <Button
              size="sm"
              variant="outline"
              className="self-start"
              onClick={() => setConditions((prev) => [...prev, emptyCondition()])}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />{t('rules.addCondition')}
            </Button>
          </fieldset>

          <fieldset className="flex flex-col gap-3 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">{t('rules.actionsLegend')}</legend>
            <p className="text-xs text-muted-foreground">{t('rules.actionsHint')}</p>
            {actions.map((action, i) => (
              <div key={i} className="flex flex-col gap-2 rounded-md border bg-muted/30 p-3">
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                    aria-expanded={!action.collapsed}
                    onClick={() => patchAction(i, { collapsed: !action.collapsed })}
                  >
                    {action.collapsed ? (
                      <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                    )}
                    <span className="text-xs font-medium">
                      {t('rules.actionN', { n: i + 1 })}
                    </span>
                    {action.collapsed && (
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {action.tool || '—'}
                      </span>
                    )}
                  </button>
                  {actions.length > 1 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t('rules.removeAction')}
                      onClick={() => setActions((prev) => prev.filter((_, j) => j !== i))}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
                {!action.collapsed && (
                  <CallFields
                    idPrefix={`rule-action-${i}`}
                    draft={action}
                    onChange={(patch) => patchAction(i, patch)}
                    testWorkspace={testWorkspace}
                  />
                )}
              </div>
            ))}
            <Button
              size="sm"
              variant="outline"
              className="self-start"
              onClick={() => setActions((prev) => [...prev, emptyCall()])}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />{t('rules.addAction')}
            </Button>
          </fieldset>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rule-next">{t('rules.chain')}</Label>
            <Select
              value={nextRuleId || 'none'}
              onValueChange={(v) => setNextRuleId(v === 'none' ? '' : v)}
            >
              <SelectTrigger id="rule-next">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t('rules.chainNone')}</SelectItem>
                {chainCandidates.map((r) => (
                  <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t('rules.chainHint')}</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={isPending || !canSubmit}>
            {isPending ? t('common.loading') : t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Dialog « Jouer la règle » ─────────────────────────────────────────────────

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? ''
}

function TraceBlock({ trace }: { trace: RuleTraceEntry }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <p className="text-sm font-medium">{trace.rule}</p>
      {trace.conditions.map((c, i) => (
        <div key={i} className="rounded-md border p-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs">{c.tool}</span>
            <Badge variant={c.ok ? 'secondary' : 'outline'} className="text-xs">
              {c.ok ? t('rules.conditionOk') : t('rules.conditionKo')}
            </Badge>
          </div>
          <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted p-2 font-mono text-xs">
            {pretty(c.result)}
          </pre>
        </div>
      ))}
      <div className="flex items-center gap-2">
        <span className="text-sm">{t('rules.traceVerdict')}</span>
        {trace.matched ? (
          <Badge className="text-xs">{t('rules.traceMatched')}</Badge>
        ) : (
          <Badge variant="secondary" className="text-xs">{t('rules.traceNotMatched')}</Badge>
        )}
      </div>
      {trace.actions.map((a, i) => (
        <div key={i} className="rounded-md border p-2">
          <p className="font-mono text-xs text-muted-foreground">
            {a.tool} {pretty(a.args)}
          </p>
          <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted p-2 font-mono text-xs">
            {pretty(a.result)}
          </pre>
        </div>
      ))}
      {trace.chain_stopped && (
        <p className="text-xs text-destructive">
          {t('rules.chainStopped')} {trace.chain_stopped}
        </p>
      )}
    </div>
  )
}

function TestRuleDialog({
  rule,
  open,
  onClose,
}: {
  rule: UserRule
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const test = useTestRule()
  const [workspace, setWorkspace] = useState('')
  const result: RuleTestResult | undefined = test.data

  function close() {
    test.reset()
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('rules.testTitle', { name: rule.name })}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="rule-test-ws">{t('rules.testWorkspace')}</Label>
            <Input
              id="rule-test-ws"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              placeholder="mon-projet"
            />
            <p className="text-xs text-muted-foreground">{t('rules.testWorkspaceHint')}</p>
          </div>
          <Button
            onClick={() =>
              test.mutate(
                { id: rule.id, workspace: workspace.trim() || null },
                {
                  onError: (e) =>
                    toast.error(e instanceof Error ? e.message : t('errors.generic')),
                },
              )
            }
            disabled={test.isPending}
          >
            <Play className="mr-1 h-4 w-4" />
            {test.isPending ? t('common.loading') : t('rules.play')}
          </Button>

          {result && !result.ok && (
            <div className="rounded-md border border-destructive p-3">
              <Badge variant="destructive" className="text-xs">{t('rules.traceError')}</Badge>
              <p className="mt-1.5 font-mono text-xs">{result.error}</p>
            </div>
          )}
          {result?.ok &&
            (result.traces ?? []).map((trace, i) => <TraceBlock key={i} trace={trace} />)}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.close')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Card règle ────────────────────────────────────────────────────────────────

function RuleCard({ rule, ruleNames }: { rule: UserRule; ruleNames: Map<string, string> }) {
  const { t } = useTranslation()
  const del = useDeleteRule()
  const clone = useCreateRule()
  const [editOpen, setEditOpen] = useState(false)
  const [testOpen, setTestOpen] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  const broken =
    rule.conditions.some((c) => !c.service_id) || rule.actions.some((a) => !a.service_id)

  function cloneRule() {
    clone.mutate(
      {
        name: `${rule.name}${t('rules.copySuffix')}`,
        enabled: rule.enabled,
        event_type: rule.event_type,
        conditions: rule.conditions.map((c) => ({ ...c, service_id: c.service_id ?? '' })),
        actions: rule.actions.map((a) => ({ ...a, service_id: a.service_id ?? '' })),
        next_rule_id: rule.next_rule_id,
      },
      {
        onSuccess: () => toast.success(t('rules.cloned')),
        onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
      },
    )
  }

  return (
    <div className="flex items-start gap-3 rounded-lg border bg-card p-4">
      <Workflow className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{rule.name}</span>
          <Badge variant="outline" className="font-mono text-xs">{rule.event_type}</Badge>
          {!rule.enabled && (
            <Badge variant="secondary" className="text-xs">{t('rules.disabled')}</Badge>
          )}
          {broken && (
            <Badge variant="destructive" className="text-xs">{t('rules.serviceMissing')}</Badge>
          )}
        </div>
        <p className="mt-0.5 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
          {t('rules.summary', {
            conditions: rule.conditions.length,
            actions: rule.actions.length,
          })}
          {rule.next_rule_id && (
            <span className="flex items-center gap-1">
              <Link2 className="h-3 w-3" />
              {t('rules.chainedTo', {
                name: ruleNames.get(rule.next_rule_id) ?? rule.next_rule_id,
              })}
            </span>
          )}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button size="sm" variant="ghost" onClick={() => setTestOpen(true)} disabled={broken}>
          <Play className="h-3.5 w-3.5" />
          <span className="ml-1">{t('rules.play')}</span>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          title={t('common.edit')}
          aria-label={t('common.edit')}
          onClick={() => setEditOpen(true)}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          title={t('rules.clone')}
          aria-label={t('rules.clone')}
          disabled={broken || clone.isPending}
          onClick={cloneRule}
        >
          <Copy className="h-3.5 w-3.5" />
        </Button>
        {confirmDel ? (
          <>
            <Button
              size="sm"
              variant="destructive"
              disabled={del.isPending}
              onClick={() =>
                del.mutate(rule.id, {
                  onSuccess: () => setConfirmDel(false),
                  onError: (e) =>
                    toast.error(e instanceof Error ? e.message : t('errors.generic')),
                })
              }
            >
              {t('rules.confirmDelete')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDel(false)}>
              {t('common.cancel')}
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => setConfirmDel(true)}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      {editOpen && (
        <RuleFormDialog rule={rule} open={editOpen} onClose={() => setEditOpen(false)} />
      )}
      {testOpen && (
        <TestRuleDialog rule={rule} open={testOpen} onClose={() => setTestOpen(false)} />
      )}
    </div>
  )
}

// ── Composant principal ───────────────────────────────────────────────────────

export default function RulesTab() {
  const { t } = useTranslation()
  const { data: rules = [], isLoading } = useRules()
  const [createOpen, setCreateOpen] = useState(false)
  const ruleNames = new Map(rules.map((r) => [r.id, r.name]))

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('rules.sectionTitle')}</h2>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />{t('rules.create')}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">{t('rules.intro')}</p>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && rules.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('rules.empty')}</p>
      )}
      <div className="flex flex-col gap-2">
        {rules.map((r) => (
          <RuleCard key={r.id} rule={r} ruleNames={ruleNames} />
        ))}
      </div>
      {createOpen && <RuleFormDialog open={createOpen} onClose={() => setCreateOpen(false)} />}
    </div>
  )
}
