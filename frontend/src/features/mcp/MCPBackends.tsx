import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Server, Plus, KeyRound, ExternalLink, Pencil, Power, PowerOff, ChevronDown, ChevronRight } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
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
import { useVaultKeys } from '@/features/vault/api'
import {
  useBackends,
  useCreateBackend,
  useUpdateBackend,
  useDeleteBackend,
  useBackendKeys,
  useCreateKey,
  useDeleteKey,
  useBackendCatalog,
  type MCPBackend,
  type MCPBackendKey,
  type StorageType,
  type Transport,
} from './api'

function AddBackendDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateBackend()
  const [namespace, setNamespace] = useState('')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [transport, setTransport] = useState<Transport>('streamable_http')
  const [appUrl, setAppUrl] = useState('')

  function close() {
    setNamespace(''); setName(''); setUrl(''); setTransport('streamable_http'); setAppUrl('')
    create.reset(); onClose()
  }

  function submit() {
    create.mutate(
      { namespace, name, url, transport, app_url: appUrl.trim() },
      { onSuccess: close, onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')) },
    )
  }

  const canSubmit = !!namespace && !!name && !!url && !create.isPending

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('mcp.backends.dialogTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.namespace')}</Label>
            <Input value={namespace} onChange={(e) => setNamespace(e.target.value)} placeholder={t('mcp.backends.namespacePlaceholder')} />
            <span className="text-xs text-muted-foreground">{t('mcp.backends.namespaceHint')}</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.name')}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.url')}</Label>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t('mcp.backends.urlPlaceholder')} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.transport')}</Label>
            <Select value={transport} onValueChange={(v) => setTransport(v as Transport)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="streamable_http">streamable_http</SelectItem>
                <SelectItem value="sse">sse</SelectItem>
                <SelectItem value="stdio">stdio</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.appUrl')}</Label>
            <Input
              type="url"
              value={appUrl}
              onChange={(e) => setAppUrl(e.target.value)}
              placeholder="https://app.example.com"
            />
            <span className="text-xs text-muted-foreground">{t('mcp.backends.appUrlHint')}</span>
          </div>
          {create.error && (
            <Alert variant="destructive">
              <AlertDescription>
                {create.error instanceof Error ? create.error.message : t('errors.generic')}
              </AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {create.isPending ? t('mcp.saving') : t('mcp.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditBackendDialog({ backend, open, onClose }: { backend: MCPBackend; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const update = useUpdateBackend()
  const isDevpod = backend.namespace === 'devpod'
  // Monté conditionnellement (clé sur l'id) → states initialisés à l'ouverture, pas d'effet.
  const [name, setName] = useState(backend.name)
  const [url, setUrl] = useState(backend.url)
  const [transport, setTransport] = useState<Transport>(backend.transport)
  const [appUrl, setAppUrl] = useState(backend.app_url)
  const [enabled, setEnabled] = useState(backend.enabled)

  function submit() {
    update.mutate(
      { id: backend.id, name, url, transport, enabled, app_url: appUrl.trim() },
      { onSuccess: onClose, onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')) },
    )
  }

  const canSubmit = !!name && (isDevpod || !!url) && !update.isPending

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('mcp.backends.editTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.namespace')}</Label>
            <Input value={backend.namespace} disabled readOnly />
            <span className="text-xs text-muted-foreground">{t('mcp.backends.namespaceImmutable')}</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.name')}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.url')}</Label>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('mcp.backends.urlPlaceholder')}
              disabled={isDevpod}
              readOnly={isDevpod}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.transport')}</Label>
            <Select value={transport} onValueChange={(v) => setTransport(v as Transport)} disabled={isDevpod}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="streamable_http">streamable_http</SelectItem>
                <SelectItem value="sse">sse</SelectItem>
                <SelectItem value="stdio">stdio</SelectItem>
                <SelectItem value="internal">internal</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {!isDevpod && (
            <div className="flex flex-col gap-1.5">
              <Label>{t('mcp.backends.appUrl')}</Label>
              <Input
                type="url"
                value={appUrl}
                onChange={(e) => setAppUrl(e.target.value)}
                placeholder="https://app.example.com"
              />
            </div>
          )}
          {!isDevpod && (
            <Button
              variant="outline"
              size="sm"
              className="w-fit gap-1.5"
              onClick={() => setEnabled((v) => !v)}
            >
              {enabled
                ? <><Power className="h-3.5 w-3.5 text-emerald-600" />{t('mcp.backends.enabledOn')}</>
                : <><PowerOff className="h-3.5 w-3.5 text-muted-foreground" />{t('mcp.backends.enabledOff')}</>}
            </Button>
          )}
          {update.error && (
            <Alert variant="destructive">
              <AlertDescription>
                {update.error instanceof Error ? update.error.message : t('errors.generic')}
              </AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {update.isPending ? t('mcp.saving') : t('mcp.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AddKeyDialog({ backendId, open, onClose }: { backendId: string; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const { data: vaultKeys = [] } = useVaultKeys()
  const create = useCreateKey(backendId)
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [storage, setStorage] = useState<StorageType>('local')
  const [vaultId, setVaultId] = useState('')
  const [value, setValue] = useState('')

  function close() {
    setSlug(''); setDescription(''); setStorage('local'); setVaultId(''); setValue('')
    create.reset(); onClose()
  }

  function submit() {
    create.mutate(
      {
        slug, description, storage_type: storage, secret_value: value,
        vault_identifier: storage === 'harpocrate' ? vaultId : null,
      },
      { onSuccess: close, onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')) },
    )
  }

  const canSubmit = !!slug && !!value && !create.isPending && (storage !== 'harpocrate' || !!vaultId)

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>{t('mcp.backends.keyDialogTitle')}</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.slug')}</Label>
            <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder={t('mcp.backends.slugPlaceholder')} />
            <span className="text-xs text-muted-foreground">{t('mcp.backends.slugHint')}</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.description')}</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.storageType')}</Label>
            <Select value={storage} onValueChange={(v) => setStorage(v as StorageType)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="local">{t('mcp.backends.storageLocal')}</SelectItem>
                <SelectItem value="harpocrate" disabled={vaultKeys.length === 0}>
                  {t('mcp.backends.storageHarpocrate')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          {storage === 'harpocrate' && (
            <div className="flex flex-col gap-1.5">
              <Label>{t('mcp.backends.wallet')}</Label>
              <Select value={vaultId} onValueChange={setVaultId}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {vaultKeys.map((k) => (
                    <SelectItem key={k.identifier} value={k.identifier}>{k.identifier}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.secretValue')}</Label>
            <Input type="password" value={value} onChange={(e) => setValue(e.target.value)} />
          </div>
          {create.error && (
            <Alert variant="destructive">
              <AlertDescription>
                {create.error instanceof Error ? create.error.message : t('errors.generic')}
              </AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {create.isPending ? t('mcp.saving') : t('mcp.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function KeyRow({ backendId, keyItem }: { backendId: string; keyItem: MCPBackendKey }) {
  const { t } = useTranslation()
  const del = useDeleteKey(backendId)
  const [confirmDel, setConfirmDel] = useState(false)

  return (
    <div className="flex items-center gap-2 text-sm">
      <KeyRound className="h-3.5 w-3.5 text-muted-foreground" />
      <code className="font-mono">{keyItem.slug}</code>
      <Badge variant="outline" className="text-xs">{keyItem.storage_type}</Badge>
      <span className="text-muted-foreground">{keyItem.description}</span>
      <div className="ml-auto flex gap-1">
        {confirmDel ? (
          <>
            <Button
              size="sm"
              variant="destructive"
              disabled={del.isPending}
              onClick={() =>
                del.mutate(keyItem.id, {
                  onSuccess: () => setConfirmDel(false),
                  onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
                })
              }
            >
              {t('mcp.backends.confirmDelete')}
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
            {t('mcp.backends.delete')}
          </Button>
        )}
      </div>
    </div>
  )
}

function KeyList({ backendId }: { backendId: string }) {
  const { t } = useTranslation()
  const { data: keys = [] } = useBackendKeys(backendId)
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="mt-2 flex flex-col gap-2 border-l pl-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase text-muted-foreground">{t('mcp.backends.keysTitle')}</span>
        <Button size="sm" variant="ghost" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-3.5 w-3.5" />{t('mcp.backends.addKey')}
        </Button>
      </div>
      {keys.length === 0 && <span className="text-xs text-muted-foreground">{t('mcp.backends.noKeys')}</span>}
      {keys.map((k) => (
        <KeyRow key={k.id} backendId={backendId} keyItem={k} />
      ))}
      <AddKeyDialog backendId={backendId} open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}

function PrimitivesList({ backendId }: { backendId: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const { data: tools = [], isLoading } = useBackendCatalog(open ? backendId : null)

  return (
    <div className="mt-1 border-l pl-3">
      <button
        type="button"
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {t('mcp.backends.viewTools')}
      </button>
      {open && (
        <div className="mt-2 flex flex-wrap gap-1">
          {isLoading && <span className="text-xs text-muted-foreground">{t('common.loading')}</span>}
          {!isLoading && tools.length === 0 && (
            <span className="text-xs text-muted-foreground">{t('mcp.backends.noTools')}</span>
          )}
          {tools.map((tool) => (
            <Badge
              key={tool.name}
              variant="secondary"
              className="font-mono text-xs cursor-default"
              title={tool.description}
            >
              {tool.name}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}

function BackendCard({ backend }: { backend: MCPBackend }) {
  const { t } = useTranslation()
  const del = useDeleteBackend()
  const [confirmDel, setConfirmDel] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const isDeletable = backend.namespace !== 'devpod'

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2">
        <Server className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium">{backend.name}</span>
        <Badge variant="outline" className="font-mono text-xs">{backend.namespace}</Badge>
        {backend.health === 'up' && (
          <Badge className="border-transparent bg-emerald-600 text-white">
            {t('mcp.backends.healthUp')}
          </Badge>
        )}
        {backend.health === 'down' && (
          <Badge variant="destructive">{t('mcp.backends.healthDown')}</Badge>
        )}
        {!backend.enabled && <Badge variant="secondary">{t('mcp.backends.statusDisabled')}</Badge>}
        <span className="ml-2 text-xs text-muted-foreground">{backend.url}</span>
        {backend.app_url && (
          <a
            href={backend.app_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-primary hover:underline"
            title={t('mcp.backends.openApp')}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {t('mcp.backends.openApp')}
          </a>
        )}
        <div className="ml-auto flex gap-1">
          {confirmDel ? (
            <>
              <Button
                size="sm"
                variant="destructive"
                disabled={del.isPending}
                onClick={() =>
                  del.mutate(backend.id, {
                    onSuccess: () => setConfirmDel(false),
                    onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
                  })
                }
              >
                {t('mcp.backends.confirmDelete')}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDel(false)}>
                {t('common.cancel')}
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditOpen(true)}
                title={t('mcp.backends.edit')}
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              {isDeletable && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setConfirmDel(true)}
                >
                  {t('mcp.backends.delete')}
                </Button>
              )}
            </>
          )}
        </div>
      </div>
      <KeyList backendId={backend.id} />
      <PrimitivesList backendId={backend.id} />
      {editOpen && (
        <EditBackendDialog backend={backend} open onClose={() => setEditOpen(false)} />
      )}
    </div>
  )
}

export default function MCPBackends() {
  const { t } = useTranslation()
  const { data: backends = [], isLoading } = useBackends()
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('mcp.backends.sectionTitle')}</h2>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />{t('mcp.backends.add')}
        </Button>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && backends.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('mcp.backends.empty')}</p>
      )}
      {backends.map((b) => (
        <BackendCard key={b.id} backend={b} />
      ))}
      <AddBackendDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}
