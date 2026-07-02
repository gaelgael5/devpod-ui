import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAdminLogs, useSaveLogs, type LogsConfig } from './useAdminLogs'

/** Formulaire monté avec les valeurs chargées (state initialisé en lazy, pas d'effet). */
function LogsForm({ initial }: { initial: LogsConfig }) {
  const { t } = useTranslation()
  const save = useSaveLogs()
  const [enabled, setEnabled] = useState(initial.enabled)
  const [lokiPushUrl, setLokiPushUrl] = useState(initial.loki_push_url)
  const [lokiQueryUrl, setLokiQueryUrl] = useState(initial.loki_query_url)
  const [grafanaUrl, setGrafanaUrl] = useState(initial.grafana_url)
  const [module, setModule] = useState(initial.module)
  const [pushToken, setPushToken] = useState('')

  const missingUrls = enabled && (!lokiPushUrl.trim() || !lokiQueryUrl.trim())

  function handleSave() {
    save.mutate(
      {
        enabled,
        loki_push_url: lokiPushUrl,
        loki_query_url: lokiQueryUrl,
        grafana_url: grafanaUrl,
        module,
        push_token: pushToken || undefined,
      },
      {
        onSuccess: () => {
          toast.success(t('admin.logs.saved'))
          setPushToken('')
        },
      },
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="logs-enabled" className="flex cursor-pointer items-center gap-3">
          <div className="relative">
            <input
              id="logs-enabled"
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
          <span className="text-sm font-medium">{t('admin.logs.enabled')}</span>
        </label>
        <p className="text-xs text-muted-foreground">{t('admin.logs.enabledHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="logs-loki-push-url">{t('admin.logs.lokiPushUrl')}</Label>
        <Input
          id="logs-loki-push-url"
          value={lokiPushUrl}
          onChange={(e) => setLokiPushUrl(e.target.value)}
          placeholder="http://192.168.10.196:3100/loki/api/v1/push"
        />
        <p className="text-xs text-muted-foreground">{t('admin.logs.lokiPushUrlHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="logs-loki-query-url">{t('admin.logs.lokiQueryUrl')}</Label>
        <Input
          id="logs-loki-query-url"
          value={lokiQueryUrl}
          onChange={(e) => setLokiQueryUrl(e.target.value)}
          placeholder="http://loki:3100"
        />
        <p className="text-xs text-muted-foreground">{t('admin.logs.lokiQueryUrlHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="logs-grafana-url">{t('admin.logs.grafanaUrl')}</Label>
        <Input
          id="logs-grafana-url"
          value={grafanaUrl}
          onChange={(e) => setGrafanaUrl(e.target.value)}
          placeholder="https://log.dev.yoops.org"
        />
        <p className="text-xs text-muted-foreground">{t('admin.logs.grafanaUrlHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="logs-module">{t('admin.logs.module')}</Label>
        <Input
          id="logs-module"
          value={module}
          onChange={(e) => setModule(e.target.value)}
          placeholder="devpod"
        />
        <p className="text-xs text-muted-foreground">{t('admin.logs.moduleHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="logs-push-token">{t('admin.logs.pushToken')}</Label>
        <Input
          id="logs-push-token"
          type="password"
          value={pushToken}
          onChange={(e) => setPushToken(e.target.value)}
          autoComplete="new-password"
          placeholder={initial.has_push_token ? t('admin.logs.pushTokenKept') : ''}
        />
        <p className="text-xs text-muted-foreground">{t('admin.logs.pushTokenHint')}</p>
      </div>

      {missingUrls && (
        <p className="text-sm text-destructive">{t('admin.logs.missingUrls')}</p>
      )}

      <div>
        <Button onClick={handleSave} disabled={save.isPending || missingUrls}>
          {save.isPending ? '…' : t('admin.logs.save')}
        </Button>
      </div>
    </div>
  )
}

export default function AdminLogs() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useAdminLogs()

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="mb-2 text-2xl font-semibold">{t('admin.logs.title')}</h1>
      <p className="mb-6 text-sm text-muted-foreground">{t('admin.logs.intro')}</p>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && <LogsForm initial={data} />}
    </div>
  )
}
