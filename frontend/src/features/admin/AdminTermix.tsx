import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { useSystemSecrets } from '@/features/automations/useAutomations'
import {
  useTermixInstances,
  type TermixInstance,
  type TermixInstanceBody,
} from './useTermixInstances'

const EMPTY: TermixInstanceBody = {
  name: '',
  url: '',
  apikey_secret: '',
  oidc_client_id: '',
  is_default: false,
}

function toBody(i: TermixInstance): TermixInstanceBody {
  return {
    name: i.name,
    url: i.url,
    apikey_secret: i.apikey_secret,
    oidc_client_id: i.oidc_client_id,
    is_default: i.is_default,
  }
}

/** Dialogue création / édition d'une instance Termix. */
function InstanceDialog({
  target,
  open,
  onClose,
}: {
  target: TermixInstance | null
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { create, update } = useTermixInstances()
  const secretsQuery = useSystemSecrets()
  const isNew = target === null

  const [form, setForm] = useState<TermixInstanceBody>(target ? toBody(target) : EMPTY)

  function set<K extends keyof TermixInstanceBody>(key: K, value: TermixInstanceBody[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  const isPending = create.isPending || update.isPending
  const canSubmit =
    form.name.trim() !== '' &&
    form.url.trim() !== '' &&
    form.apikey_secret !== '' &&
    /^https?:\/\//.test(form.url.trim())

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    const done = { onSuccess: onClose }
    if (isNew) create.mutate(form, done)
    else update.mutate({ id: target.id, body: form }, done)
  }

  const secrets = secretsQuery.data ?? []

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isNew ? t('admin.termix.add') : t('admin.termix.edit')}
          </DialogTitle>
          <DialogDescription>{t('admin.termix.dialogHint')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tx-name">{t('admin.termix.name')}</Label>
            <Input
              id="tx-name"
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="termix-portail"
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tx-url">{t('admin.termix.url')}</Label>
            <Input
              id="tx-url"
              type="url"
              value={form.url}
              onChange={(e) => set('url', e.target.value)}
              placeholder="https://termix.yoops.org"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tx-secret">{t('admin.termix.apikeySecret')}</Label>
            <Select value={form.apikey_secret} onValueChange={(v) => set('apikey_secret', v)}>
              <SelectTrigger id="tx-secret">
                <SelectValue placeholder={t('admin.termix.apikeySecretPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {secrets.map((s) => (
                  <SelectItem key={s.slug} value={s.slug}>
                    {s.label} ({s.slug})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t('admin.termix.apikeySecretHint')}</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tx-oidc">{t('admin.termix.oidcClientId')}</Label>
            <Input
              id="tx-oidc"
              value={form.oidc_client_id}
              onChange={(e) => set('oidc_client_id', e.target.value)}
              placeholder="termix"
            />
            <p className="text-xs text-muted-foreground">{t('admin.termix.oidcClientIdHint')}</p>
          </div>
          <div className="flex items-center justify-between rounded-md border px-3 py-2">
            <div>
              <Label htmlFor="tx-default">{t('admin.termix.isDefault')}</Label>
              <p className="text-xs text-muted-foreground">{t('admin.termix.isDefaultHint')}</p>
            </div>
            <Switch
              id="tx-default"
              checked={form.is_default}
              onCheckedChange={(v) => set('is_default', v)}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button type="submit" disabled={isPending || !canSubmit}>
              {t('admin.form.save')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default function AdminTermix() {
  const { t } = useTranslation()
  const { listQuery, remove } = useTermixInstances()
  const { data: instances, isLoading, isError } = listQuery

  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState<TermixInstance | null>(null)

  function openNew() {
    setTarget(null)
    setOpen(true)
  }

  function openEdit(i: TermixInstance) {
    setTarget(i)
    setOpen(true)
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('admin.termix.title')}</h1>
        <Button size="sm" onClick={openNew}>
          {t('admin.termix.add')}
        </Button>
      </div>
      <p className="mb-6 text-sm text-muted-foreground">{t('admin.termix.intro')}</p>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !instances?.length && (
        <p className="text-muted-foreground">{t('admin.termix.empty')}</p>
      )}

      {instances && instances.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                  {t('admin.termix.name')}
                </th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                  {t('admin.termix.url')}
                </th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                  {t('admin.termix.apikeySecret')}
                </th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {instances.map((i) => (
                <tr key={i.id} className="border-b last:border-0">
                  <td className="px-4 py-2 font-medium">
                    {i.name}
                    {i.is_default && (
                      <Badge variant="secondary" className="ml-2">
                        {t('admin.termix.defaultBadge')}
                      </Badge>
                    )}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{i.url}</td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                    {i.apikey_secret}
                  </td>
                  <td className="flex items-center justify-end gap-1 px-4 py-2 text-right">
                    <Button size="sm" variant="ghost" onClick={() => openEdit(i)}>
                      {t('workspaces.actions.edit')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => remove.mutate(i.id)}
                      disabled={remove.isPending}
                    >
                      {t('workspaces.actions.delete')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && (
        <InstanceDialog target={target} open={open} onClose={() => setOpen(false)} />
      )}
    </div>
  )
}
