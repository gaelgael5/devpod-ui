import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import JsonEditor from '@/features/profiles/components/JsonEditor'
import {
  useContract,
  useContracts,
  useCreateAutomation,
  useCreateSystemSecret,
  useEventTypes,
  useSystemSecrets,
  useTestCall,
  useUpdateAutomation,
  type Automation,
  type AutomationInput,
  type HeaderRow,
  type Operation,
} from './useAutomations'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

// Variables de contexte proposées comme raccourcis (event courant → template).
const VARIABLES = [
  'actor',
  'workspace',
  'type',
  'subject.login',
  'subject.sub',
  'subject.email',
  'subject.host_name',
  'subject.address',
]

const SELECT_CLS =
  'h-9 w-full rounded-md border border-input bg-background px-2 text-sm ' +
  'ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

function slugify(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}

interface HeaderDraft {
  name: string
  value: string
  secretRef: string
  valuePrefix: string
  isSecret: boolean
  required: boolean
  enabled: boolean
}

function toDrafts(headers: HeaderRow[]): HeaderDraft[] {
  return headers.map((h) => ({
    name: h.name,
    value: h.value ?? '',
    secretRef: h.secret_ref ?? '',
    valuePrefix: h.value_prefix ?? '',
    isSecret: h.secret_ref != null || (h.value == null && !!h.value_prefix),
    required: h.required ?? false,
    enabled: h.enabled ?? true,
  }))
}

function draftsToRows(drafts: HeaderDraft[]): HeaderRow[] {
  return drafts
    .filter((h) => h.name.trim())
    .map((h) => ({
      name: h.name.trim(),
      value: h.isSecret ? null : h.value || null,
      secret_ref: h.isSecret ? h.secretRef || null : null,
      value_prefix: h.valuePrefix || undefined,
      required: h.required,
      enabled: h.enabled,
    }))
}

// ─── Arbre des events (groupés par domaine `user.*`, `workspace.*`, …) ──────────

function EventsTree({
  codes,
  selected,
  onToggle,
}: {
  codes: string[]
  selected: string[]
  onToggle: (code: string) => void
}) {
  const groups = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const code of codes) {
      const domain = code.includes('.') ? code.split('.')[0] : 'autre'
      m.set(domain, [...(m.get(domain) ?? []), code])
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [codes])

  return (
    <div className="max-h-64 space-y-1 overflow-y-auto rounded-md border p-2">
      {groups.map(([domain, members]) => (
        <details key={domain} open className="group">
          <summary className="cursor-pointer select-none text-xs font-semibold text-muted-foreground">
            {domain}
          </summary>
          <div className="ml-3 mt-1 space-y-1 border-l pl-3">
            {members.map((code) => (
              <label key={code} className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(code)}
                  onChange={() => onToggle(code)}
                />
                <span className="font-mono text-xs">{code}</span>
              </label>
            ))}
          </div>
        </details>
      ))}
    </div>
  )
}

// ─── Sélecteur de secret système (+ création inline) ────────────────────────────

function SecretPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useTranslation()
  const secrets = useSystemSecrets()
  const createSecret = useCreateSystemSecret()
  const [creating, setCreating] = useState(false)
  const [slug, setSlug] = useState('')
  const [labelTxt, setLabelTxt] = useState('')
  const [secretValue, setSecretValue] = useState('')

  const known = secrets.data ?? []
  const orphan = value && !known.some((s) => `\${system://${s.slug}}` === value)

  function doCreate() {
    const s = slugify(slug || labelTxt)
    if (!s || !secretValue) return
    createSecret.mutate(
      { slug: s, label: labelTxt || s, value: secretValue },
      {
        onSuccess: (r) => {
          onChange(r.ref)
          setCreating(false)
          setSlug('')
          setLabelTxt('')
          setSecretValue('')
          toast.success(t('automations.form.secretCreated'))
        },
      },
    )
  }

  return (
    <div className="min-w-0 flex-1 space-y-1">
      <div className="flex items-center gap-1">
        <select value={value} onChange={(e) => onChange(e.target.value)} className={SELECT_CLS}>
          <option value="">{t('automations.form.chooseSecret')}</option>
          {known.map((s) => (
            <option key={s.slug} value={`\${system://${s.slug}}`}>
              {s.label}
            </option>
          ))}
          {orphan && <option value={value}>{value}</option>}
        </select>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setCreating((c) => !c)}
          title={t('automations.form.newSecret')}
        >
          ＋
        </Button>
      </div>
      {creating && (
        <div className="flex flex-wrap items-center gap-1 rounded-md border p-2">
          <Input
            className="h-8 w-28"
            placeholder={t('automations.form.secretSlug')}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
          <Input
            className="h-8 w-28"
            placeholder={t('automations.form.secretLabel')}
            value={labelTxt}
            onChange={(e) => setLabelTxt(e.target.value)}
          />
          <Input
            className="h-8 flex-1"
            type="password"
            placeholder={t('automations.form.secretValue')}
            value={secretValue}
            onChange={(e) => setSecretValue(e.target.value)}
          />
          <Button type="button" size="sm" onClick={doCreate} disabled={createSecret.isPending}>
            {t('automations.form.createSecret')}
          </Button>
        </div>
      )}
    </div>
  )
}

// ─── Éditeur d'en-têtes ─────────────────────────────────────────────────────────

function HeadersEditor({
  headers,
  setHeaders,
}: {
  headers: HeaderDraft[]
  setHeaders: React.Dispatch<React.SetStateAction<HeaderDraft[]>>
}) {
  const { t } = useTranslation()
  const patch = (i: number, p: Partial<HeaderDraft>) =>
    setHeaders((hs) => hs.map((h, j) => (i === j ? { ...h, ...p } : h)))

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <Label>{t('automations.form.headers')}</Label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            setHeaders((h) => [
              ...h,
              {
                name: '',
                value: '',
                secretRef: '',
                valuePrefix: '',
                isSecret: false,
                required: false,
                enabled: true,
              },
            ])
          }
        >
          {t('automations.form.addHeader')}
        </Button>
      </div>
      {headers.map((h, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2 rounded-md border p-2">
          <Input
            className="w-40"
            placeholder={t('automations.form.headerName')}
            value={h.name}
            onChange={(e) => patch(i, { name: e.target.value })}
          />
          <Input
            className="w-24 font-mono text-xs"
            placeholder={t('automations.form.headerPrefix')}
            title={t('automations.form.headerPrefixHint')}
            value={h.valuePrefix}
            onChange={(e) => patch(i, { valuePrefix: e.target.value })}
          />
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={h.isSecret}
              onChange={(e) => patch(i, { isSecret: e.target.checked })}
            />
            {t('automations.form.secret')}
          </label>
          {h.isSecret ? (
            <SecretPicker value={h.secretRef} onChange={(v) => patch(i, { secretRef: v })} />
          ) : (
            <Input
              className="min-w-0 flex-1"
              placeholder={t('automations.form.headerValue')}
              value={h.value}
              onChange={(e) => patch(i, { value: e.target.value })}
            />
          )}
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={h.enabled}
              onChange={(e) => patch(i, { enabled: e.target.checked })}
            />
            {t('automations.form.enabled')}
          </label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setHeaders((hs) => hs.filter((_, j) => j !== i))}
          >
            ✕
          </Button>
        </div>
      ))}
    </div>
  )
}

export function AutomationDialog({
  automation,
  open,
  onOpenChange,
}: {
  automation: Automation | null
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { t } = useTranslation()
  const isEdit = automation !== null
  const contracts = useContracts()
  const eventTypes = useEventTypes()
  const create = useCreateAutomation()
  const update = useUpdateAutomation()
  const testCall = useTestCall()

  const [tab, setTab] = useState('general')
  const [label, setLabel] = useState(automation?.label ?? '')
  const [slug, setSlug] = useState(automation?.slug ?? '')
  const [slugTouched, setSlugTouched] = useState(isEdit)
  const [events, setEvents] = useState<string[]>(automation?.event_types ?? [])
  const [priority, setPriority] = useState(String(automation?.position ?? 0))
  const [delay, setDelay] = useState(String(automation?.delay_minutes ?? 0))
  const [stopChain, setStopChain] = useState(automation?.stop_chain ?? false)
  const [active, setActive] = useState(automation?.active ?? false)

  const [contractRef, setContractRef] = useState(automation?.contract_ref ?? '')
  const [operationId, setOperationId] = useState(automation?.operation_id ?? '')
  const [url, setUrl] = useState(automation?.url ?? '')
  const [method, setMethod] = useState(automation?.http_method ?? 'POST')
  const [bodyTemplate, setBodyTemplate] = useState(automation?.body_template ?? '')
  const [headers, setHeaders] = useState<HeaderDraft[]>(toDrafts(automation?.headers ?? []))
  const [copiedVar, setCopiedVar] = useState<string | null>(null)

  const [filterContractRef, setFilterContractRef] = useState(automation?.filter_contract_ref ?? '')
  const [filterOperationId, setFilterOperationId] = useState(automation?.filter_operation_id ?? '')
  const [filterUrl, setFilterUrl] = useState(automation?.filter_url ?? '')
  const [filterMethod, setFilterMethod] = useState(automation?.filter_method ?? 'GET')
  const [filterBody, setFilterBody] = useState(automation?.filter_body ?? '')

  const detail = useContract(contractRef || null)
  const filterDetail = useContract(filterContractRef || null)

  // Slug suit le libellé tant que l'utilisateur ne l'a pas édité manuellement.
  function onLabelChange(v: string) {
    setLabel(v)
    if (!slugTouched) setSlug(slugify(v))
  }

  function toggleEvent(code: string) {
    setEvents((c) => (c.includes(code) ? c.filter((x) => x !== code) : [...c, code]))
  }

  function addAuthHeaders(op: Operation) {
    if (!op.auth_headers?.length) return
    setHeaders((prev) => {
      const names = new Set(prev.map((h) => h.name.toLowerCase()))
      const add: HeaderDraft[] = op.auth_headers
        .filter((a) => !names.has(a.header.toLowerCase()))
        .map((a) => ({
          name: a.header,
          value: '',
          secretRef: '',
          valuePrefix: a.value_prefix,
          isSecret: true,
          required: true,
          enabled: true,
        }))
      return add.length ? [...prev, ...add] : prev
    })
  }

  function selectOperation(opId: string) {
    setOperationId(opId)
    const op = detail.data?.operations.find((o) => o.operation_id === opId)
    if (!op) return
    setMethod(op.method)
    if (op.body_skeleton != null) setBodyTemplate(JSON.stringify(op.body_skeleton, null, 2))
    const server = detail.data?.servers?.[0]
    if (server) {
      const base = server.replace(/\/+$/, '')
      const path = op.path.startsWith('/') ? op.path : `/${op.path}`
      setUrl(`${base}${path}`)
    } else {
      setUrl(op.url)
    }
    addAuthHeaders(op)
  }

  function selectFilterOperation(opId: string) {
    setFilterOperationId(opId)
    const op = filterDetail.data?.operations.find((o) => o.operation_id === opId)
    if (!op) return
    setFilterMethod(op.method)
    const server = filterDetail.data?.servers?.[0]
    setFilterUrl(server ? `${server.replace(/\/+$/, '')}${op.path}` : op.url)
    if (op.body_skeleton != null) setFilterBody(JSON.stringify(op.body_skeleton, null, 2))
  }

  async function copyVariable(v: string) {
    try {
      await navigator.clipboard?.writeText(`{${v}}`)
      setCopiedVar(v)
      setTimeout(() => setCopiedVar(null), 1200)
    } catch {
      /* presse-papier indisponible */
    }
  }

  function runTest() {
    if (!filterUrl.trim()) return
    testCall.mutate({
      url: filterUrl.trim(),
      http_method: filterMethod,
      headers: draftsToRows(headers),
      body: filterBody.trim() || null,
    })
  }

  function submit() {
    if (!label.trim() || events.length === 0 || !contractRef || !operationId || !url.trim()) {
      toast.error(t('automations.form.missing'))
      return
    }
    const body: AutomationInput = {
      label: label.trim(),
      slug: slug.trim() || undefined,
      event_types: events,
      contract_ref: contractRef,
      operation_id: operationId,
      url: url.trim(),
      http_method: method,
      body_template: bodyTemplate.trim() ? bodyTemplate : null,
      delay_minutes: Number(delay) || 0,
      position: Number(priority) || 0,
      stop_chain: stopChain,
      headers: draftsToRows(headers),
      active,
      filter_contract_ref: filterContractRef || null,
      filter_operation_id: filterOperationId || null,
      filter_url: filterUrl.trim() || null,
      filter_method: filterUrl.trim() ? filterMethod : null,
      filter_body: filterBody.trim() || null,
    }
    const onSuccess = () => {
      onOpenChange(false)
      toast.success(isEdit ? t('automations.form.updated') : t('automations.form.created'))
    }
    if (isEdit) update.mutate({ id: automation.id, body }, { onSuccess })
    else create.mutate(body, { onSuccess })
  }

  const pending = create.isPending || update.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] flex-col overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t('automations.form.editTitle') : t('automations.form.newTitle')}
          </DialogTitle>
        </DialogHeader>

        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
          <TabsList className="w-full">
            <TabsTrigger value="general" className="flex-1">
              {t('automations.form.tabGeneral')}
            </TabsTrigger>
            <TabsTrigger value="filter" className="flex-1">
              {t('automations.form.tabFilter')}
            </TabsTrigger>
            <TabsTrigger value="call" className="flex-1">
              {t('automations.form.tabCall')}
            </TabsTrigger>
          </TabsList>

          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            {/* ── Général ── */}
            <TabsContent value="general" className="mt-3 flex flex-col gap-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="au-label">{t('automations.form.label')}</Label>
                  <Input id="au-label" value={label} onChange={(e) => onLabelChange(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="au-slug">{t('automations.form.slug')}</Label>
                  <Input
                    id="au-slug"
                    value={slug}
                    onChange={(e) => {
                      setSlugTouched(true)
                      setSlug(e.target.value)
                    }}
                    className="font-mono text-xs"
                  />
                  <p className="text-xs text-muted-foreground">{t('automations.form.slugHint')}</p>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>{t('automations.form.events')}</Label>
                <EventsTree
                  codes={eventTypes.data ?? []}
                  selected={events}
                  onToggle={toggleEvent}
                />
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="au-priority">{t('automations.form.priority')}</Label>
                  <Input
                    id="au-priority"
                    type="number"
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t('automations.form.priorityHint')}
                  </p>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="au-delay">{t('automations.form.delay')}</Label>
                  <Input
                    id="au-delay"
                    type="number"
                    min={0}
                    value={delay}
                    onChange={(e) => setDelay(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">{t('automations.form.delayHint')}</p>
                </div>
              </div>

              <div className="flex flex-col gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <Switch checked={stopChain} onCheckedChange={setStopChain} />
                  {t('automations.form.stopChain')}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Switch checked={active} onCheckedChange={setActive} />
                  {t('automations.form.active')}
                </label>
              </div>
            </TabsContent>

            {/* ── Filtre ── */}
            <TabsContent value="filter" className="mt-3 flex flex-col gap-4">
              <p className="text-xs text-muted-foreground">{t('automations.form.filterIntro')}</p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label>{t('automations.form.contract')}</Label>
                  <select
                    className={SELECT_CLS}
                    value={filterContractRef}
                    onChange={(e) => {
                      setFilterContractRef(e.target.value)
                      setFilterOperationId('')
                    }}
                  >
                    <option value="">—</option>
                    {contracts.data?.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>{t('automations.form.operation')}</Label>
                  <select
                    className={SELECT_CLS}
                    value={filterOperationId}
                    onChange={(e) => selectFilterOperation(e.target.value)}
                    disabled={!filterContractRef}
                  >
                    <option value="">—</option>
                    {filterDetail.data?.operations.map((op) => (
                      <option key={op.operation_id} value={op.operation_id}>
                        {op.method} {op.path}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_8rem]">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="fi-url">{t('automations.form.url')}</Label>
                  <Input id="fi-url" value={filterUrl} onChange={(e) => setFilterUrl(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>{t('automations.form.method')}</Label>
                  <select
                    className={SELECT_CLS}
                    value={filterMethod}
                    onChange={(e) => setFilterMethod(e.target.value)}
                  >
                    {METHODS.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="fi-body">{t('automations.form.bodyTemplate')}</Label>
                <Textarea
                  id="fi-body"
                  value={filterBody}
                  onChange={(e) => setFilterBody(e.target.value)}
                  rows={3}
                  className="font-mono text-xs"
                />
              </div>

              <div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={runTest}
                  disabled={testCall.isPending || !filterUrl.trim()}
                >
                  {testCall.isPending
                    ? t('automations.form.filterTesting')
                    : t('automations.form.filterTest')}
                </Button>
              </div>

              <div>
                {testCall.data ? (
                  testCall.data.ok ? (
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground">
                        {t('automations.form.filterStatus')} : {testCall.data.status_code}
                      </p>
                      <pre className="max-h-56 overflow-auto rounded-md border bg-muted p-2 font-mono text-xs">
                        {testCall.data.body}
                      </pre>
                    </div>
                  ) : (
                    <p className="text-xs text-destructive">
                      {t('automations.form.filterError')} : {testCall.data.error}
                    </p>
                  )
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {t('automations.form.filterNoResult')}
                  </p>
                )}
              </div>
            </TabsContent>

            {/* ── Appel ── */}
            <TabsContent value="call" className="mt-3 flex flex-col gap-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label>{t('automations.form.contract')}</Label>
                  <select
                    className={SELECT_CLS}
                    value={contractRef}
                    onChange={(e) => {
                      setContractRef(e.target.value)
                      setOperationId('')
                    }}
                  >
                    <option value="">—</option>
                    {contracts.data?.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>{t('automations.form.operation')}</Label>
                  <select
                    className={SELECT_CLS}
                    value={operationId}
                    onChange={(e) => selectOperation(e.target.value)}
                    disabled={!contractRef}
                  >
                    <option value="">—</option>
                    {detail.data?.operations.map((op) => (
                      <option key={op.operation_id} value={op.operation_id}>
                        {op.method} {op.path}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_8rem]">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="au-url">{t('automations.form.url')}</Label>
                  <Input id="au-url" value={url} onChange={(e) => setUrl(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>{t('automations.form.method')}</Label>
                  <select
                    className={SELECT_CLS}
                    value={method}
                    onChange={(e) => setMethod(e.target.value)}
                  >
                    {METHODS.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="au-body">{t('automations.form.bodyTemplate')}</Label>
                  <div className="flex flex-wrap justify-end gap-1">
                    <span className="mr-1 text-xs text-muted-foreground">
                      {t('automations.form.variables')} :
                    </span>
                    {VARIABLES.map((v) => (
                      <button
                        key={v}
                        type="button"
                        onClick={() => copyVariable(v)}
                        className={`rounded px-1.5 py-0.5 font-mono text-xs transition-colors ${
                          copiedVar === v
                            ? 'bg-primary/20 text-primary'
                            : 'bg-muted hover:bg-muted-foreground/20'
                        }`}
                      >
                        {copiedVar === v ? '✓' : `{${v}}`}
                      </button>
                    ))}
                  </div>
                </div>
                <JsonEditor value={bodyTemplate} onChange={setBodyTemplate} />
                <p className="text-xs text-muted-foreground">{t('automations.form.bodyHint')}</p>
              </div>

              <HeadersEditor headers={headers} setHeaders={setHeaders} />
            </TabsContent>
          </div>
        </Tabs>

        <div className="flex justify-end border-t pt-3">
          <Button onClick={submit} disabled={pending}>
            {pending ? '…' : t('common.save')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
