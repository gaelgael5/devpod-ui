import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  useContract,
  useContracts,
  useCreateContract,
  useDeleteContract,
  useRefreshContract,
  useUpdateContract,
  type Contract,
} from './useAutomations'

function ImportDialog() {
  const { t } = useTranslation()
  const create = useCreateContract()
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [category, setCategory] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [rawSpec, setRawSpec] = useState('')

  function submit() {
    const body: { label: string; category?: string; source_url?: string; raw_spec?: unknown } = {
      label,
      category: category.trim() || undefined,
    }
    if (rawSpec.trim()) {
      try {
        body.raw_spec = JSON.parse(rawSpec)
      } catch {
        toast.error(t('automations.contracts.invalidJson'))
        return
      }
    } else if (sourceUrl.trim()) {
      body.source_url = sourceUrl.trim()
    } else {
      toast.error(t('automations.contracts.needUrlOrSpec'))
      return
    }
    create.mutate(body, {
      onSuccess: () => {
        setOpen(false)
        setLabel('')
        setCategory('')
        setSourceUrl('')
        setRawSpec('')
        toast.success(t('automations.contracts.imported'))
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>{t('automations.contracts.import')}</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('automations.contracts.importTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ct-label">{t('automations.contracts.label')}</Label>
            <Input id="ct-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ct-category">{t('automations.contracts.category')}</Label>
            <Input
              id="ct-category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder={t('automations.contracts.categoryPlaceholder')}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ct-url">{t('automations.contracts.sourceUrl')}</Label>
            <Input
              id="ct-url"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://api.example.org/openapi.json"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ct-spec">{t('automations.contracts.pasteSpec')}</Label>
            <Textarea
              id="ct-spec"
              value={rawSpec}
              onChange={(e) => setRawSpec(e.target.value)}
              rows={6}
              placeholder='{"openapi":"3.0.0", ...}'
            />
            <p className="text-xs text-muted-foreground">{t('automations.contracts.pasteHint')}</p>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!label.trim() || create.isPending}>
            {create.isPending ? '…' : t('automations.contracts.doImport')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function OperationsDialog({ contract }: { contract: Contract }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const { data } = useContract(open ? contract.id : null)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          {t('automations.contracts.operations')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{contract.label}</DialogTitle>
        </DialogHeader>
        <div className="max-h-96 overflow-y-auto">
          {!data && <p className="text-sm text-muted-foreground">…</p>}
          {data?.operations.map((op) => (
            <div key={op.operation_id} className="border-b py-2 text-sm last:border-0">
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{op.method}</Badge>
                <code className="font-mono text-xs">{op.path}</code>
              </div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {op.operation_id}
                {op.summary ? ` — ${op.summary}` : ''}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function EditDialog({ contract }: { contract: Contract }) {
  const { t } = useTranslation()
  const update = useUpdateContract()
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState(contract.label)
  const [category, setCategory] = useState(contract.category ?? '')
  const [sourceUrl, setSourceUrl] = useState(contract.source_url ?? '')

  function submit() {
    const body: { label?: string; category?: string; source_url?: string } = {}
    if (label.trim() && label !== contract.label) body.label = label.trim()
    if (category !== (contract.category ?? '')) body.category = category.trim()
    if (sourceUrl !== (contract.source_url ?? '')) body.source_url = sourceUrl.trim()
    if (Object.keys(body).length === 0) {
      setOpen(false)
      return
    }
    update.mutate(
      { id: contract.id, body },
      {
        onSuccess: () => {
          setOpen(false)
          toast.success(t('automations.contracts.updated'))
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          {t('common.edit')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('automations.contracts.editTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-label">{t('automations.contracts.label')}</Label>
            <Input id="edit-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-category">{t('automations.contracts.category')}</Label>
            <Input
              id="edit-category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder={t('automations.contracts.categoryPlaceholder')}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="edit-url">{t('automations.contracts.sourceUrl')}</Label>
            <Input
              id="edit-url"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              placeholder="https://…/openapi.json"
            />
            <p className="text-xs text-muted-foreground">{t('automations.contracts.editUrlHint')}</p>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!label.trim() || update.isPending}>
            {update.isPending ? '…' : t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ContractRow({ contract: c }: { contract: Contract }) {
  const { t } = useTranslation()
  const refresh = useRefreshContract()
  const del = useDeleteContract()
  return (
    <div className="flex items-center justify-between rounded-md border p-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium">{c.label}</span>
          {c.version && <Badge variant="secondary">v{c.version}</Badge>}
        </div>
        {c.source_url && (
          <code className="block truncate text-xs text-muted-foreground">{c.source_url}</code>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <OperationsDialog contract={c} />
        <EditDialog contract={c} />
        {c.source_url && (
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              refresh.mutate(c.id, {
                onSuccess: () => toast.success(t('automations.contracts.refreshed')),
              })
            }
            disabled={refresh.isPending}
          >
            {t('automations.contracts.refresh')}
          </Button>
        )}
        <Button
          variant="destructive"
          size="sm"
          onClick={() => {
            if (confirm(t('automations.contracts.confirmDelete', { label: c.label }))) {
              del.mutate(c.id, {
                onSuccess: () => toast.success(t('automations.contracts.deleted')),
              })
            }
          }}
          disabled={del.isPending}
        >
          {t('common.delete')}
        </Button>
      </div>
    </div>
  )
}

/** Regroupe les contrats par catégorie (les sans-catégorie en dernier), triés. */
function groupByCategory(contracts: Contract[]): { key: string; items: Contract[] }[] {
  const map = new Map<string, Contract[]>()
  for (const c of contracts) {
    const key = c.category?.trim() || ''
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(c)
  }
  return [...map.entries()]
    .sort(([a], [b]) => {
      if (a === '') return 1
      if (b === '') return -1
      return a.localeCompare(b)
    })
    .map(([key, items]) => ({ key, items }))
}

export default function AdminContracts() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useContracts()
  const groups = groupByCategory(data ?? [])

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('automations.contracts.title')}</h1>
        <ImportDialog />
      </div>
      <p className="mb-6 text-sm text-muted-foreground">{t('automations.contracts.intro')}</p>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && data.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('automations.contracts.empty')}</p>
      )}

      <div className="flex flex-col gap-6">
        {groups.map((g) => (
          <div key={g.key || '__none__'} className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              {g.key || t('automations.contracts.uncategorized')}
            </h2>
            {g.items.map((c) => (
              <ContractRow key={c.id} contract={c} />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
