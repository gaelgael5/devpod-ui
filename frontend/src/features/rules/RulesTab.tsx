import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Play, Plus, Trash2, Workflow } from 'lucide-react'
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
  useTestRule, useUpdateRule,
  type RuleOperator, type RuleTrace, type UserRule,
} from './api'

const OPERATORS: RuleOperator[] = ['eq', 'neq', 'contains', 'not_contains']

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

// ── Sélecteur service + outil + args (sonde et action ont la même forme) ──────

function PrimitiveFields({
  idPrefix,
  legend,
  serviceId,
  setServiceId,
  tool,
  setTool,
  args,
  setArgs,
}: {
  idPrefix: string
  legend: string
  serviceId: string
  setServiceId: (v: string) => void
  tool: string
  setTool: (v: string) => void
  args: string
  setArgs: (v: string) => void
}) {
  const { t } = useTranslation()
  const { data: services = [] } = useServices()
  const { data: tools = [] } = useServiceTools(serviceId)
  const argsInvalid = parseArgs(args) === null

  return (
    <fieldset className="flex flex-col gap-3 rounded-md border p-3">
      <legend className="px-1 text-sm font-medium">{legend}</legend>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-service`}>{t('rules.service')}</Label>
        <Select
          value={serviceId}
          onValueChange={(v) => {
            setServiceId(v)
            setTool('')
          }}
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
        <Select value={tool} onValueChange={setTool} disabled={!serviceId}>
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
        {!!serviceId && tools.length === 0 && (
          <p className="text-xs text-muted-foreground">{t('rules.noTools')}</p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-args`}>{t('rules.args')}</Label>
        <textarea
          id={`${idPrefix}-args`}
          value={args}
          onChange={(e) => setArgs(e.target.value)}
          rows={3}
          spellCheck={false}
          placeholder='{"workspace_slug": "{workspace}"}'
          className="rounded-md border bg-transparent px-3 py-2 font-mono text-xs"
        />
        {argsInvalid && <p className="text-xs text-destructive">{t('rules.argsInvalid')}</p>}
        <p className="text-xs text-muted-foreground">{t('rules.argsHint')}</p>
      </div>
    </fieldset>
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
  const create = useCreateRule()
  const update = useUpdateRule()

  const [name, setName] = useState(rule?.name ?? '')
  const [eventType, setEventType] = useState(rule?.event_type ?? '')
  const [probeService, setProbeService] = useState(rule?.probe_service_id ?? '')
  const [probeTool, setProbeTool] = useState(rule?.probe_tool ?? '')
  const [probeArgs, setProbeArgs] = useState(JSON.stringify(rule?.probe_args ?? {}, null, 0))
  const [condPath, setCondPath] = useState(rule?.condition_path ?? '')
  const [condOperator, setCondOperator] = useState<RuleOperator>(
    rule?.condition_operator ?? 'not_contains',
  )
  const [condValue, setCondValue] = useState(rule?.condition_value ?? '')
  const [actionService, setActionService] = useState(rule?.action_service_id ?? '')
  const [actionTool, setActionTool] = useState(rule?.action_tool ?? '')
  const [actionArgs, setActionArgs] = useState(JSON.stringify(rule?.action_args ?? {}, null, 0))

  const isPending = create.isPending || update.isPending

  function close() {
    create.reset()
    update.reset()
    onClose()
  }

  const parsedProbeArgs = parseArgs(probeArgs)
  const parsedActionArgs = parseArgs(actionArgs)
  const canSubmit =
    !!name.trim() && !!eventType && !!probeService && !!probeTool &&
    !!actionService && !!actionTool && parsedProbeArgs !== null && parsedActionArgs !== null

  function submit() {
    if (parsedProbeArgs === null || parsedActionArgs === null) return
    const body = {
      name: name.trim(),
      enabled: rule?.enabled ?? true,
      event_type: eventType,
      probe: { service_id: probeService, tool: probeTool, args: parsedProbeArgs },
      condition: { path: condPath.trim(), operator: condOperator, value: condValue },
      action: { service_id: actionService, tool: actionTool, args: parsedActionArgs },
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
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{rule ? t('rules.editTitle') : t('rules.createTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
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

          <PrimitiveFields
            idPrefix="rule-probe"
            legend={t('rules.probeLegend')}
            serviceId={probeService}
            setServiceId={setProbeService}
            tool={probeTool}
            setTool={setProbeTool}
            args={probeArgs}
            setArgs={setProbeArgs}
          />

          <fieldset className="flex flex-col gap-3 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">{t('rules.conditionLegend')}</legend>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rule-cond-path">{t('rules.conditionPath')}</Label>
              <Input
                id="rule-cond-path"
                value={condPath}
                onChange={(e) => setCondPath(e.target.value)}
                placeholder="slug"
              />
              <p className="text-xs text-muted-foreground">{t('rules.conditionPathHint')}</p>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rule-cond-op">{t('rules.conditionOperator')}</Label>
              <Select value={condOperator} onValueChange={(v) => setCondOperator(v as RuleOperator)}>
                <SelectTrigger id="rule-cond-op">
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
              <Label htmlFor="rule-cond-value">{t('rules.conditionValue')}</Label>
              <Input
                id="rule-cond-value"
                value={condValue}
                onChange={(e) => setCondValue(e.target.value)}
                placeholder="{workspace}"
              />
            </div>
            <p className="text-xs text-muted-foreground">{t('rules.conditionHint')}</p>
          </fieldset>

          <PrimitiveFields
            idPrefix="rule-action"
            legend={t('rules.actionLegend')}
            serviceId={actionService}
            setServiceId={setActionService}
            tool={actionTool}
            setTool={setActionTool}
            args={actionArgs}
            setArgs={setActionArgs}
          />
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
  const trace: RuleTrace | undefined = test.data

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

          {trace && !trace.ok && (
            <div className="rounded-md border border-destructive p-3">
              <Badge variant="destructive" className="text-xs">{t('rules.traceError')}</Badge>
              <p className="mt-1.5 font-mono text-xs">{trace.error}</p>
            </div>
          )}
          {trace?.ok && (
            <div className="flex flex-col gap-3">
              <div className="rounded-md border p-3">
                <p className="text-sm font-medium">{t('rules.traceProbe')}</p>
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  {trace.probe?.tool} {pretty(trace.probe?.args)}
                </p>
                <pre className="mt-1.5 max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-xs">
                  {pretty(trace.probe?.result)}
                </pre>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{t('rules.traceVerdict')}</span>
                {trace.matched ? (
                  <Badge className="text-xs">{t('rules.traceMatched')}</Badge>
                ) : (
                  <Badge variant="secondary" className="text-xs">
                    {t('rules.traceNotMatched')}
                  </Badge>
                )}
              </div>
              {trace.matched && trace.action && (
                <div className="rounded-md border p-3">
                  <p className="text-sm font-medium">{t('rules.traceAction')}</p>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {trace.action.tool} {pretty(trace.action.args)}
                  </p>
                  <pre className="mt-1.5 max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-xs">
                    {pretty(trace.action.result)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.close')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Card règle ────────────────────────────────────────────────────────────────

function RuleCard({ rule }: { rule: UserRule }) {
  const { t } = useTranslation()
  const del = useDeleteRule()
  const [editOpen, setEditOpen] = useState(false)
  const [testOpen, setTestOpen] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  const broken = !rule.probe_service_id || !rule.action_service_id

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
        <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
          {rule.probe_tool} → {t(`rules.op.${rule.condition_operator}`)}
          {rule.condition_value ? ` "${rule.condition_value}"` : ''} → {rule.action_tool}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button size="sm" variant="ghost" onClick={() => setTestOpen(true)} disabled={broken}>
          <Play className="h-3.5 w-3.5" />
          <span className="ml-1">{t('rules.play')}</span>
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setEditOpen(true)}>
          <Pencil className="h-3.5 w-3.5" />
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
          <RuleCard key={r.id} rule={r} />
        ))}
      </div>
      {createOpen && <RuleFormDialog open={createOpen} onClose={() => setCreateOpen(false)} />}
    </div>
  )
}
