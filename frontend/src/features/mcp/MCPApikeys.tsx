import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Key, Plus, Copy, Check, Ban, Clock } from 'lucide-react'
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
  useSetApikeyProfile,
  useProfiles,
  type MCPApikey,
} from './api'

const NO_PROFILE = '__none__'

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(iso))
}

function CreateApikeyDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateApikey()
  const { data: profiles = [] } = useProfiles()
  const [label, setLabel] = useState('')
  const [profileId, setProfileId] = useState<string>(NO_PROFILE)
  const [token, setToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  function close() {
    setLabel('')
    setProfileId(NO_PROFILE)
    setToken(null)
    setCopied(false)
    create.reset()
    onClose()
  }

  function submit() {
    create.mutate(
      { label, profile_id: profileId === NO_PROFILE ? null : profileId },
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
            <div className="flex flex-col gap-1.5">
              <Label>{t('mcp.apikeys.profile')}</Label>
              <Select value={profileId} onValueChange={setProfileId}>
                <SelectTrigger>
                  <SelectValue placeholder={t('mcp.apikeys.profilePlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_PROFILE}>{t('mcp.apikeys.noProfile')}</SelectItem>
                  {profiles.map((p) => (
                    <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
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

function ApikeyCard({ apikey }: { apikey: MCPApikey }) {
  const { t } = useTranslation()
  const revoke = useRevokeApikey()
  const del = useDeleteApikey()
  const setProfile = useSetApikeyProfile()
  const { data: profiles = [] } = useProfiles()
  const [confirmDel, setConfirmDel] = useState(false)

  const profileName = apikey.profile_id
    ? profiles.find((p) => p.id === apikey.profile_id)?.name ?? apikey.profile_id
    : null

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <Key className="h-4 w-4 shrink-0 text-muted-foreground" />
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

      {!apikey.revoked && (
        <div className="mt-2 flex items-center gap-2 border-l pl-3">
          <span className="text-xs text-muted-foreground shrink-0">{t('mcp.apikeys.profile')}</span>
          <Select
            value={apikey.profile_id ?? NO_PROFILE}
            onValueChange={(v) => {
              if (v === undefined || v === null) return
              setProfile.mutate(
                { id: apikey.id, profile_id: v === NO_PROFILE ? null : v },
                { onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')) },
              )
            }}
          >
            <SelectTrigger className="h-7 text-xs flex-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_PROFILE}>{t('mcp.apikeys.noProfile')}</SelectItem>
              {profiles.map((p) => (
                <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {profileName && (
            <Badge variant="outline" className="text-xs shrink-0">{profileName}</Badge>
          )}
        </div>
      )}

      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 border-l pl-3">
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="h-3 w-3 shrink-0" />
          {t('mcp.apikeys.connectedAt')} {fmtDate(apikey.created_at)}
        </span>
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="h-3 w-3 shrink-0" />
          {t('mcp.apikeys.lastCall')} {fmtDate(apikey.last_used_at)}
        </span>
      </div>
    </div>
  )
}

export default function MCPApikeys({ kind = 'apikey' }: { kind?: 'apikey' | 'oauth' }) {
  const { t } = useTranslation()
  const { data: allApikeys = [], isLoading } = useApikeys()
  const [addOpen, setAddOpen] = useState(false)

  const apikeys = allApikeys.filter((a) => (a.kind ?? 'apikey') === kind)
  const isBearer = kind === 'apikey'

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">
          {isBearer ? t('mcp.apikeys.sectionTitle') : t('mcp.apikeys.oauthSectionTitle')}
        </h2>
        {isBearer && (
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="mr-1 h-4 w-4" />{t('mcp.apikeys.add')}
          </Button>
        )}
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && apikeys.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('mcp.apikeys.empty')}</p>
      )}
      {apikeys.map((a) => (
        <ApikeyCard key={a.id} apikey={a} />
      ))}
      {isBearer && <CreateApikeyDialog open={addOpen} onClose={() => setAddOpen(false)} />}
    </div>
  )
}
