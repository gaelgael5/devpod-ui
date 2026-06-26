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

  function handleSave() {
    save.mutate(
      { base_domain: baseDomain, external_url: externalUrl, workspace_host: workspaceHost },
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
