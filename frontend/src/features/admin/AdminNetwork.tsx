import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAdminNetwork, useSaveNetwork, type NetworkConfig } from './useAdminNetwork'

/** Formulaire monté avec les valeurs chargées (state initialisé en lazy, pas d'effet). */
function NetworkForm({ initial }: { initial: NetworkConfig }) {
  const { t } = useTranslation()
  const save = useSaveNetwork()
  const [baseDomain, setBaseDomain] = useState(initial.base_domain)
  const [externalUrl, setExternalUrl] = useState(initial.external_url)
  const [workspaceHost, setWorkspaceHost] = useState(initial.workspace_host)
  const [devMode, setDevMode] = useState(initial.dev_mode)
  const [vsProxyDomain, setVsProxyDomain] = useState(initial.vs_proxy_domain)
  const [cookieDomain, setCookieDomain] = useState(initial.cookie_domain)

  function handleSave() {
    save.mutate(
      {
        base_domain: baseDomain,
        external_url: externalUrl,
        workspace_host: workspaceHost,
        dev_mode: devMode,
        vs_proxy_domain: vsProxyDomain,
        cookie_domain: cookieDomain,
      },
      { onSuccess: () => toast.success(t('admin.network.saved')) },
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="net-base-domain">{t('admin.network.baseDomain')}</Label>
        <Input
          id="net-base-domain"
          value={baseDomain}
          onChange={(e) => setBaseDomain(e.target.value)}
          placeholder="dev.yoops.org"
        />
        <p className="text-xs text-muted-foreground">{t('admin.network.baseDomainHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="net-external-url">{t('admin.network.externalUrl')}</Label>
        <Input
          id="net-external-url"
          value={externalUrl}
          onChange={(e) => setExternalUrl(e.target.value)}
          placeholder="https://dev.yoops.org"
        />
        <p className="text-xs text-muted-foreground">{t('admin.network.externalUrlHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="net-workspace-host">{t('admin.network.workspaceHost')}</Label>
        <Input
          id="net-workspace-host"
          value={workspaceHost}
          onChange={(e) => setWorkspaceHost(e.target.value)}
          placeholder="192.168.10.50"
        />
        <p className="text-xs text-muted-foreground">{t('admin.network.workspaceHostHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="net-cookie-domain">{t('admin.network.cookieDomain')}</Label>
        <Input
          id="net-cookie-domain"
          value={cookieDomain}
          onChange={(e) => setCookieDomain(e.target.value)}
          placeholder="yoops.org"
        />
        <p className="text-xs text-muted-foreground">{t('admin.network.cookieDomainHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="net-vs-proxy-domain">{t('admin.network.vsProxyDomain')}</Label>
        <Input
          id="net-vs-proxy-domain"
          value={vsProxyDomain}
          onChange={(e) => setVsProxyDomain(e.target.value)}
          placeholder="vs-dev.yoops.org"
        />
        <p className="text-xs text-muted-foreground">{t('admin.network.vsProxyDomainHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="net-dev-mode" className="flex cursor-pointer items-center gap-3">
          <div className="relative">
            <input
              id="net-dev-mode"
              type="checkbox"
              className="sr-only"
              checked={devMode}
              onChange={(e) => setDevMode(e.target.checked)}
            />
            <div
              className={`h-6 w-11 rounded-full transition-colors ${devMode ? 'bg-primary' : 'bg-input'}`}
            />
            <div
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${devMode ? 'translate-x-5' : 'translate-x-0.5'}`}
            />
          </div>
          <span className="text-sm font-medium">{t('admin.network.devMode')}</span>
        </label>
        <p className="text-xs text-muted-foreground">{t('admin.network.devModeHint')}</p>
      </div>

      <div>
        <Button onClick={handleSave} disabled={save.isPending}>
          {save.isPending ? '…' : t('admin.network.save')}
        </Button>
      </div>
    </div>
  )
}

export default function AdminNetwork() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useAdminNetwork()

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="mb-2 text-2xl font-semibold">{t('admin.network.title')}</h1>
      <p className="mb-6 text-sm text-muted-foreground">{t('admin.network.intro')}</p>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && <NetworkForm initial={data} />}
    </div>
  )
}
