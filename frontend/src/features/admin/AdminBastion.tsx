import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAdminBastion, useSaveBastion, type BastionConfig } from './useAdminBastion'

function BastionForm({ initial }: { initial: BastionConfig }) {
  const { t } = useTranslation()
  const save = useSaveBastion()
  const [enabled, setEnabled] = useState(initial.enabled)
  const [apiUrl, setApiUrl] = useState(initial.api_url)
  const [host, setHost] = useState(initial.host)
  const [port, setPort] = useState(String(initial.port))
  const [role, setRole] = useState(initial.role)
  const [apikeySecret, setApikeySecret] = useState(initial.apikey_secret)

  const missing = enabled && (!apiUrl.trim() || !host.trim() || !role.trim())

  function handleSave() {
    save.mutate(
      {
        enabled,
        api_url: apiUrl.trim(),
        host: host.trim(),
        port: Number(port) || 2222,
        role: role.trim(),
        apikey_secret: apikeySecret.trim() || 'termix-apikey',
      },
      { onSuccess: () => toast.success(t('admin.bastion.saved')) },
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="bastion-enabled" className="flex cursor-pointer items-center gap-3">
          <div className="relative">
            <input
              id="bastion-enabled"
              type="checkbox"
              className="sr-only"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <div
              className={`h-6 w-11 rounded-full transition-colors ${enabled ? 'bg-primary' : 'bg-input'}`}
            />
            <div
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${enabled ? 'translate-x-5' : 'translate-x-0.5'}`}
            />
          </div>
          <span className="text-sm font-medium">{t('admin.bastion.enabled')}</span>
        </label>
        <p className="text-xs text-muted-foreground">{t('admin.bastion.enabledHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="bastion-api-url">{t('admin.bastion.apiUrl')}</Label>
        <Input
          id="bastion-api-url"
          value={apiUrl}
          onChange={(e) => setApiUrl(e.target.value)}
          placeholder="https://termix.yoops.org"
        />
        <p className="text-xs text-muted-foreground">{t('admin.bastion.apiUrlHint')}</p>
      </div>

      <div className="grid grid-cols-[1fr_8rem] gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="bastion-host">{t('admin.bastion.host')}</Label>
          <Input
            id="bastion-host"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="192.168.10.164"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="bastion-port">{t('admin.bastion.port')}</Label>
          <Input
            id="bastion-port"
            type="number"
            value={port}
            onChange={(e) => setPort(e.target.value)}
          />
        </div>
      </div>
      <p className="-mt-2 text-xs text-muted-foreground">{t('admin.bastion.hostHint')}</p>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="bastion-role">{t('admin.bastion.role')}</Label>
        <Input
          id="bastion-role"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          placeholder="devpod-users"
        />
        <p className="text-xs text-muted-foreground">{t('admin.bastion.roleHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="bastion-apikey">{t('admin.bastion.apikeySecret')}</Label>
        <Input
          id="bastion-apikey"
          value={apikeySecret}
          onChange={(e) => setApikeySecret(e.target.value)}
          placeholder="termix-apikey"
          className="font-mono text-xs"
        />
        <p className="text-xs text-muted-foreground">{t('admin.bastion.apikeySecretHint')}</p>
      </div>

      {missing && <p className="text-sm text-destructive">{t('admin.bastion.missing')}</p>}

      <div>
        <Button onClick={handleSave} disabled={save.isPending || missing}>
          {save.isPending ? '…' : t('admin.bastion.save')}
        </Button>
      </div>
    </div>
  )
}

export default function AdminBastion() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useAdminBastion()

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="mb-2 text-2xl font-semibold">{t('admin.bastion.title')}</h1>
      <p className="mb-6 text-sm text-muted-foreground">{t('admin.bastion.intro')}</p>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && <BastionForm initial={data} />}
    </div>
  )
}
