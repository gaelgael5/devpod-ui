import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
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
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  useContract,
  useContracts,
  useCreateAutomation,
  useEventTypes,
  useUpdateAutomation,
  type Automation,
  type AutomationInput,
  type HeaderRow,
} from './useAutomations'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

interface HeaderDraft {
  name: string
  isSecret: boolean
  value: string
}

function toDrafts(headers: HeaderRow[]): HeaderDraft[] {
  return headers.map((h) => ({
    name: h.name,
    isSecret: h.secret_ref != null,
    value: (h.secret_ref ?? h.value ?? '') as string,
  }))
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

  const [label, setLabel] = useState(automation?.label ?? '')
  const [events, setEvents] = useState<string[]>(automation?.event_types ?? [])
  const [scopes, setScopes] = useState((automation?.scopes ?? ['*']).join(', '))
  const [contractRef, setContractRef] = useState(automation?.contract_ref ?? '')
  const [operationId, setOperationId] = useState(automation?.operation_id ?? '')
  const [url, setUrl] = useState(automation?.url ?? '')
  const [method, setMethod] = useState(automation?.http_method ?? 'POST')
  const [bodyTemplate, setBodyTemplate] = useState(automation?.body_template ?? '')
  const [delay, setDelay] = useState(String(automation?.delay_minutes ?? 0))
  const [stopChain, setStopChain] = useState(automation?.stop_chain ?? false)
  const [active, setActive] = useState(automation?.active ?? false)
  const [headers, setHeaders] = useState<HeaderDraft[]>(toDrafts(automation?.headers ?? []))

  const detail = useContract(contractRef || null)

  function toggleEvent(code: string) {
    setEvents((c) => (c.includes(code) ? c.filter((x) => x !== code) : [...c, code]))
  }

  function onOperation(opId: string) {
    setOperationId(opId)
    const op = detail.data?.operations.find((o) => o.operation_id === opId)
    if (op) {
      setUrl(op.url)
      setMethod(op.method)
    }
  }

  function setHeader(i: number, patch: Partial<HeaderDraft>) {
    setHeaders((hs) => hs.map((h, j) => (i === j ? { ...h, ...patch } : h)))
  }

  function submit() {
    const scopeList = scopes
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    if (!label.trim() || events.length === 0 || !contractRef || !operationId || !url.trim()) {
      toast.error(t('automations.form.missing'))
      return
    }
    if (scopeList.length === 0) {
      toast.error(t('automations.form.scopeRequired'))
      return
    }
    const headerRows: HeaderRow[] = headers
      .filter((h) => h.name.trim())
      .map((h) =>
        h.isSecret
          ? { name: h.name.trim(), secret_ref: h.value }
          : { name: h.name.trim(), value: h.value },
      )
    const body: AutomationInput = {
      label: label.trim(),
      event_types: events,
      scopes: scopeList,
      contract_ref: contractRef,
      operation_id: operationId,
      url: url.trim(),
      http_method: method,
      body_template: bodyTemplate.trim() ? bodyTemplate : null,
      delay_minutes: Number(delay) || 0,
      stop_chain: stopChain,
      headers: headerRows,
      active,
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
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t('automations.form.editTitle') : t('automations.form.newTitle')}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="au-label">{t('automations.form.label')}</Label>
            <Input id="au-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>{t('automations.form.events')}</Label>
            <div className="grid grid-cols-1 gap-1.5 rounded-md border p-3 sm:grid-cols-2">
              {eventTypes.data?.map((code) => (
                <label key={code} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={events.includes(code)}
                    onChange={() => toggleEvent(code)}
                  />
                  <span className="font-mono text-xs">{code}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="au-scopes">{t('automations.form.scopes')}</Label>
            <Input id="au-scopes" value={scopes} onChange={(e) => setScopes(e.target.value)} />
            <p className="text-xs text-muted-foreground">{t('automations.form.scopesHint')}</p>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>{t('automations.form.contract')}</Label>
              <Select
                value={contractRef}
                onValueChange={(v) => {
                  setContractRef(v)
                  setOperationId('')
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent>
                  {contracts.data?.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t('automations.form.operation')}</Label>
              <Select value={operationId} onValueChange={onOperation} disabled={!contractRef}>
                <SelectTrigger>
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent>
                  {detail.data?.operations.map((op) => (
                    <SelectItem key={op.operation_id} value={op.operation_id}>
                      {op.method} {op.path}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_8rem]">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="au-url">{t('automations.form.url')}</Label>
              <Input id="au-url" value={url} onChange={(e) => setUrl(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t('automations.form.method')}</Label>
              <Select value={method} onValueChange={setMethod}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {METHODS.map((m) => (
                    <SelectItem key={m} value={m}>
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="au-body">{t('automations.form.bodyTemplate')}</Label>
            <Textarea
              id="au-body"
              value={bodyTemplate}
              onChange={(e) => setBodyTemplate(e.target.value)}
              rows={5}
              placeholder='{"host":"{subject.host_name}","addr":"{subject.address}"}'
              className="font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">{t('automations.form.bodyHint')}</p>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <Label>{t('automations.form.headers')}</Label>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setHeaders((h) => [...h, { name: '', isSecret: false, value: '' }])}
              >
                {t('automations.form.addHeader')}
              </Button>
            </div>
            {headers.map((h, i) => (
              <div key={i} className="flex items-center gap-2">
                <Input
                  className="w-40"
                  placeholder={t('automations.form.headerName')}
                  value={h.name}
                  onChange={(e) => setHeader(i, { name: e.target.value })}
                />
                <Input
                  className="flex-1"
                  placeholder={h.isSecret ? '${vault://…}' : t('automations.form.headerValue')}
                  value={h.value}
                  onChange={(e) => setHeader(i, { value: e.target.value })}
                />
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={h.isSecret}
                    onChange={(e) => setHeader(i, { isSecret: e.target.checked })}
                  />
                  {t('automations.form.secret')}
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setHeaders((hs) => hs.filter((_, j) => j !== i))}
                >
                  ✕
                </Button>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
            <div className="flex flex-col justify-end gap-3">
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={stopChain} onCheckedChange={setStopChain} />
                {t('automations.form.stopChain')}
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={active} onCheckedChange={setActive} />
                {t('automations.form.active')}
              </label>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button onClick={submit} disabled={pending}>
            {pending ? '…' : t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
