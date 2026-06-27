import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Key, Plus, Trash2, Copy, Check, Ban, Power, PowerOff } from 'lucide-react'
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
import {
  useApikeys,
  useCreateApikey,
  useRevokeApikey,
  useDeleteApikey,
  useBackends,
  useBackendKeys,
  useGrants,
  useSetGrant,
  useDeleteGrant,
  type MCPApikey,
  type ExposeMode,
  type MCPScope,
  MCP_SCOPES,
} from './api'
import { ExposeEditor } from './ExposeEditor'

function CreateApikeyDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateApikey()
  const [label, setLabel] = useState('')
  const [token, setToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  function close() {
    setLabel('')
    setToken(null)
    setCopied(false)
    create.reset()
    onClose()
  }

  function submit() {
    create.mutate(
      { label },
      {
        onSuccess: (r) => setToken(r.token),
        onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
      },
    )
  }

  function copy() {
    if (token) {
      void navigator.clipboard.writeText(token)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {token ? t('mcp.apikeys.tokenOnceTitle') : t('mcp.apikeys.dialogTitle')}
          </DialogTitle>
        </DialogHeader>
        {token ? (
          <div className="flex flex-col gap-3">
            <Alert>
              <AlertDescription>{t('mcp.apikeys.tokenOnceWarning')}</AlertDescription>
            </Alert>
            <div className="flex items-center gap-1 rounded bg-muted/50 p-2">
              <code className="flex-1 break-all text-xs select-all">{token}</code>
              <Button size="sm" variant="ghost" onClick={copy}>
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={close}>{t('common.close')}</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label>{t('mcp.apikeys.label')}</Label>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('mcp.apikeys.labelPlaceholder')}
              />
            </div>
            {create.error && (
              <Alert variant="destructive">
                <AlertDescription>
                  {create.error instanceof Error ? create.error.message : t('errors.generic')}
                </AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
              <Button onClick={submit} disabled={create.isPending}>
                {create.isPending ? t('mcp.saving') : t('mcp.save')}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// Éditeur de grants : une ligne par serveur, avec un select de clé. C'est l'UX
// « accès à un ensemble de services avec sélection de la clé à utiliser ».
function GrantEditor({ apikeyId }: { apikeyId: string }) {
  const { t } = useTranslation()
  const { data: backends = [] } = useBackends()
  const { data: grants = [] } = useGrants(apikeyId)
  const setGrant = useSetGrant(apikeyId)
  const delGrant = useDeleteGrant(apikeyId)

  return (
    <div className="mt-2 flex flex-col gap-2 border-l pl-3">
      <span className="text-xs font-semibold uppercase text-muted-foreground">
        {t('mcp.apikeys.grantsTitle')}
      </span>
      <span className="text-xs text-muted-foreground">{t('mcp.apikeys.grantsHint')}</span>
      {backends.length === 0 && (
        <span className="text-xs text-muted-foreground">{t('mcp.apikeys.noGrants')}</span>
      )}
      {backends.map((b) => {
        const current = grants.find((g) => g.backend_id === b.id)
        return (
          <GrantRow
            key={b.id}
            backendId={b.id}
            backendName={b.name}
            namespace={b.namespace}
            granted={current !== undefined}
            currentKeyId={current?.backend_key_id ?? null}
            currentExposeMode={current?.expose_mode ?? 'all'}
            currentExpose={current?.expose ?? []}
            currentEnabled={current?.enabled ?? true}
            currentScopes={current?.scopes ?? null}
            isInternal={b.transport === 'internal'}
            onSet={(body) =>
              setGrant.mutate(
                { backend_id: b.id, ...body },
                {
                  onError: (e) =>
                    toast.error(e instanceof Error ? e.message : t('errors.generic')),
                },
              )
            }
            onRemove={() =>
              delGrant.mutate(b.id, {
                onError: (e) =>
                  toast.error(e instanceof Error ? e.message : t('errors.generic')),
              })
            }
          />
        )
      })}
    </div>
  )
}

// Valeur sentinelle pour l'option « accès public sans clé » (shadcn Select
// interdit une SelectItem de value="").
const PUBLIC_GRANT = '__public__'

type GrantBody = {
  backend_key_id: string | null
  expose_mode: ExposeMode
  expose: string[]
  enabled: boolean
  scopes: MCPScope[] | null
}

function GrantRow({
  backendId,
  backendName,
  namespace,
  granted,
  currentKeyId,
  currentExposeMode,
  currentExpose,
  currentEnabled,
  currentScopes,
  isInternal,
  onSet,
  onRemove,
}: {
  backendId: string
  backendName: string
  namespace: string
  granted: boolean
  currentKeyId: string | null
  currentExposeMode: ExposeMode
  currentExpose: string[]
  currentEnabled: boolean
  currentScopes: MCPScope[] | null
  isInternal: boolean
  onSet: (body: GrantBody) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const { data: keys = [] } = useBackendKeys(backendId)

  // Valeur affichée : aucune si pas de grant ; PUBLIC_GRANT si grant sans clé ;
  // sinon l'id de la clé choisie.
  const keyValue = !granted ? '' : (currentKeyId ?? PUBLIC_GRANT)

  // Émet l'état complet courant (clé + curation + activation) avec un override partiel :
  // le grant est ré-écrit à chaque changement (mutation immédiate, comme le choix de clé).
  const emit = (over: Partial<GrantBody>) =>
    onSet({
      backend_key_id: currentKeyId,
      expose_mode: currentExposeMode,
      expose: currentExpose,
      enabled: currentEnabled,
      scopes: currentScopes,
      ...over,
    })

  // Grisé quand le service est accordé mais désactivé temporairement.
  const dimmed = granted && !currentEnabled

  return (
    <div className="flex flex-col gap-2 border-b pb-2 last:border-0">
      <div className={`flex items-center gap-2 text-sm ${dimmed ? 'opacity-60' : ''}`}>
        <span className="font-medium">{backendName}</span>
        <Badge variant="outline" className="font-mono text-xs">{namespace}</Badge>
        {dimmed && <Badge variant="secondary">{t('mcp.apikeys.serviceDisabled')}</Badge>}
        <Select
          value={keyValue}
          onValueChange={(v) => emit({ backend_key_id: v === PUBLIC_GRANT ? null : v })}
        >
          <SelectTrigger className="ml-auto h-8 w-44">
            <SelectValue placeholder={t('mcp.apikeys.selectKey')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={PUBLIC_GRANT}>{t('mcp.apikeys.publicAccess')}</SelectItem>
            {keys.map((k) => (
              <SelectItem key={k.id} value={k.id}>{k.slug}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {granted && (
          <Button
            size="sm"
            variant="ghost"
            title={currentEnabled ? t('mcp.apikeys.disableService') : t('mcp.apikeys.enableService')}
            onClick={() => emit({ enabled: !currentEnabled })}
          >
            {currentEnabled
              ? <Power className="h-3.5 w-3.5 text-emerald-600" />
              : <PowerOff className="h-3.5 w-3.5 text-muted-foreground" />}
          </Button>
        )}
        {granted && (
          <Button size="sm" variant="ghost" className="text-destructive" onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
      {granted && (
        <div className="flex flex-col gap-1.5 pl-1">
          <Select
            value={currentExposeMode}
            onValueChange={(v) => emit({ expose_mode: v as ExposeMode })}
          >
            <SelectTrigger aria-label={t('mcp.apikeys.exposeModeLabel')} className="h-8 w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('mcp.apikeys.exposeModeAll')}</SelectItem>
              <SelectItem value="allowlist">{t('mcp.apikeys.exposeModeAllowlist')}</SelectItem>
              <SelectItem value="denylist">{t('mcp.apikeys.exposeModeDenylist')}</SelectItem>
            </SelectContent>
          </Select>
          {currentExposeMode !== 'all' && (
            <ExposeEditor value={currentExpose} onChange={(next) => emit({ expose: next })} />
          )}
          {isInternal && (
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <span className="text-xs font-semibold uppercase text-muted-foreground">
                {t('mcp.apikeys.scopesLabel')}
              </span>
              {MCP_SCOPES.map((s) => (
                <label key={s} className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={(currentScopes ?? []).includes(s)}
                    onChange={() => {
                      const base = currentScopes ?? []
                      const next = base.includes(s)
                        ? base.filter((x) => x !== s)
                        : [...base, s]
                      emit({ scopes: next })
                    }}
                  />
                  <code>{s}</code>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ApikeyCard({ apikey }: { apikey: MCPApikey }) {
  const { t } = useTranslation()
  const revoke = useRevokeApikey()
  const del = useDeleteApikey()
  const [confirmDel, setConfirmDel] = useState(false)

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2">
        <Key className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium">{apikey.label || apikey.id}</span>
        {apikey.revoked && <Badge variant="secondary">{t('mcp.apikeys.revoked')}</Badge>}
        {!apikey.revoked && (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={() =>
              revoke.mutate(apikey.id, {
                onError: (e) =>
                  toast.error(e instanceof Error ? e.message : t('errors.generic')),
              })
            }
          >
            <Ban className="mr-1 h-3.5 w-3.5" />{t('mcp.apikeys.revoke')}
          </Button>
        )}
        <div className={`${apikey.revoked ? 'ml-auto' : ''} flex gap-1`}>
          {confirmDel ? (
            <>
              <Button
                size="sm"
                variant="destructive"
                disabled={del.isPending}
                onClick={() =>
                  del.mutate(apikey.id, {
                    onSuccess: () => setConfirmDel(false),
                    onError: (e) =>
                      toast.error(e instanceof Error ? e.message : t('errors.generic')),
                  })
                }
              >
                {t('mcp.apikeys.confirmDelete')}
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
              {t('mcp.apikeys.delete')}
            </Button>
          )}
        </div>
      </div>
      {!apikey.revoked && <GrantEditor apikeyId={apikey.id} />}
    </div>
  )
}

export default function MCPApikeys() {
  const { t } = useTranslation()
  const { data: apikeys = [], isLoading } = useApikeys()
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('mcp.apikeys.sectionTitle')}</h2>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />{t('mcp.apikeys.add')}
        </Button>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && apikeys.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('mcp.apikeys.empty')}</p>
      )}
      {apikeys.map((a) => (
        <ApikeyCard key={a.id} apikey={a} />
      ))}
      <CreateApikeyDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}
