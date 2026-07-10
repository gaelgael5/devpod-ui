import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  useAdminWorkflow,
  useSaveWorkflow,
  type EventsProducerConfig,
} from './useAdminWorkflow'

/** URL de découverte à enregistrer dans Workflow (source « Discovery »). Lecture seule. */
function DiscoveryUrl({ url }: { url: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }

  return (
    <div className="mb-5 flex flex-col gap-1.5 rounded-md border bg-muted/40 p-3">
      <Label>{t('admin.workflow.discoveryLabel')}</Label>
      <div className="flex items-center gap-2">
        <code className="flex-1 truncate rounded bg-background px-2 py-1.5 font-mono text-sm">
          {url}
        </code>
        <Button variant="outline" size="sm" onClick={copy}>
          {copied ? t('admin.workflow.copied') : t('admin.workflow.copy')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t('admin.workflow.discoveryHint')}</p>
    </div>
  )
}

/** Formulaire monté avec les valeurs chargées (state initialisé en lazy, pas d'effet). */
function WorkflowForm({ initial }: { initial: EventsProducerConfig }) {
  const { t } = useTranslation()
  const save = useSaveWorkflow()
  const [enabled, setEnabled] = useState(initial.enabled)
  const [baseUrl, setBaseUrl] = useState(initial.workflow_base_url)
  const [sourceId, setSourceId] = useState(initial.source_id)
  const [sourceUri, setSourceUri] = useState(initial.source_uri)
  const [events, setEvents] = useState<string[]>(initial.events)
  const [secret, setSecret] = useState('')

  const hasSecret = initial.has_secret || secret.trim() !== ''
  // Activer exige le contrat complet — mêmes règles que le backend (fail closed).
  const missing =
    enabled && (!baseUrl.trim() || !sourceId.trim() || events.length === 0 || !hasSecret)

  function toggleEvent(code: string) {
    setEvents((cur) => (cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code]))
  }

  function handleSave() {
    save.mutate(
      {
        enabled,
        workflow_base_url: baseUrl,
        source_id: sourceId,
        source_uri: sourceUri,
        events,
        secret: secret || undefined,
      },
      {
        onSuccess: () => {
          toast.success(t('admin.workflow.saved'))
          setSecret('')
        },
      },
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="wf-enabled" className="flex cursor-pointer items-center gap-3">
          <div className="relative">
            <input
              id="wf-enabled"
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
          <span className="text-sm font-medium">{t('admin.workflow.enabled')}</span>
        </label>
        <p className="text-xs text-muted-foreground">{t('admin.workflow.enabledHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="wf-base-url">{t('admin.workflow.baseUrl')}</Label>
        <Input
          id="wf-base-url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://workflow.yoops.org"
        />
        <p className="text-xs text-muted-foreground">{t('admin.workflow.baseUrlHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="wf-source-id">{t('admin.workflow.sourceId')}</Label>
        <Input
          id="wf-source-id"
          value={sourceId}
          onChange={(e) => setSourceId(e.target.value)}
          placeholder="00000000-0000-0000-0000-000000000000"
        />
        <p className="text-xs text-muted-foreground">{t('admin.workflow.sourceIdHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="wf-source-uri">{t('admin.workflow.sourceUri')}</Label>
        <Input
          id="wf-source-uri"
          value={sourceUri}
          onChange={(e) => setSourceUri(e.target.value)}
          placeholder="urn:yoops:devpod"
        />
        <p className="text-xs text-muted-foreground">{t('admin.workflow.sourceUriHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <Label>{t('admin.workflow.events')}</Label>
          <div className="flex gap-3 text-xs">
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground"
              onClick={() => setEvents([...initial.available_events])}
            >
              {t('admin.workflow.selectAll')}
            </button>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground"
              onClick={() => setEvents([])}
            >
              {t('admin.workflow.selectNone')}
            </button>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-1.5 rounded-md border p-3 sm:grid-cols-2">
          {initial.available_events.map((code) => (
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
        <p className="text-xs text-muted-foreground">{t('admin.workflow.eventsHint')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="wf-secret">{t('admin.workflow.secret')}</Label>
        <Input
          id="wf-secret"
          type="password"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          autoComplete="new-password"
          placeholder={initial.has_secret ? t('admin.workflow.secretKept') : ''}
        />
        <p className="text-xs text-muted-foreground">{t('admin.workflow.secretHint')}</p>
      </div>

      {missing && <p className="text-sm text-destructive">{t('admin.workflow.missing')}</p>}

      <div>
        <Button onClick={handleSave} disabled={save.isPending || missing}>
          {save.isPending ? '…' : t('admin.workflow.save')}
        </Button>
      </div>
    </div>
  )
}

export default function AdminWorkflow() {
  const { t } = useTranslation()
  const { data, isLoading, isError } = useAdminWorkflow()

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="mb-2 text-2xl font-semibold">{t('admin.workflow.title')}</h1>
      <p className="mb-6 text-sm text-muted-foreground">{t('admin.workflow.intro')}</p>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {data && (
        <>
          <DiscoveryUrl url={data.discovery_url} />
          <WorkflowForm initial={data} />
        </>
      )}
    </div>
  )
}
