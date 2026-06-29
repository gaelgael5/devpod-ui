import { useTranslation } from 'react-i18next'
import { Network, Copy, CheckCircle2, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import MCPBackends from './MCPBackends'
import MCPApikeys from './MCPApikeys'
import MCPProfiles from './MCPProfiles'

function OAuthProcedure({
  provider,
  steps,
  gatewayUrl,
  copyUrl,
  settingsUrl,
}: {
  provider: string
  steps: number
  gatewayUrl: string
  copyUrl: () => void
  settingsUrl: string
}) {
  const { t } = useTranslation()
  return (
    <div className="rounded-lg border p-5 flex flex-col gap-4">
      <h2 className="text-sm font-semibold">{t(`mcp.oauth.${provider}.procedureTitle`)}</h2>
      <ol className="flex flex-col gap-4">
        {Array.from({ length: steps }, (_, i) => i + 1).map((step) => (
          <li key={step} className="flex items-start gap-3">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
              {step}
            </span>
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">
                {t(`mcp.oauth.${provider}.step${step}.title`)}
              </span>
              <span className="text-xs text-muted-foreground">
                {t(`mcp.oauth.${provider}.step${step}.desc`)}
              </span>
              {step === 1 && (
                <div className="mt-1.5 flex items-center gap-2">
                  <code className="truncate rounded border bg-muted px-2 py-0.5 text-xs font-mono">
                    {gatewayUrl}
                  </code>
                  <Button type="button" variant="ghost" size="sm" className="h-6 px-2" onClick={copyUrl}>
                    <Copy className="h-3 w-3" />
                  </Button>
                </div>
              )}
              {step === 2 && (
                <a
                  href={settingsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <ExternalLink className="h-3 w-3" />
                  {t('mcp.oauth.openSettings')}
                </a>
              )}
            </div>
          </li>
        ))}
      </ol>
      <div className="flex items-start gap-2 rounded-md border border-green-200 bg-green-50 px-4 py-3 dark:border-green-900 dark:bg-green-950/30">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600 dark:text-green-400" />
        <p className="text-xs text-green-800 dark:text-green-300">{t(`mcp.oauth.${provider}.note`)}</p>
      </div>
    </div>
  )
}

export default function MCPTab() {
  const { t } = useTranslation()
  const gatewayUrl = `${window.location.origin}/mcp`

  async function copyUrl() {
    await navigator.clipboard.writeText(gatewayUrl)
    toast.success(t('mcp.gatewayUrlCopied'))
  }

  async function copyText(text: string) {
    await navigator.clipboard.writeText(text)
    toast.success(t('mcp.copy'))
  }

  const claudeJsonSnippet = `{
  "mcpServers": {
    "devpod": {
      "url": "${gatewayUrl}",
      "headers": {
        "Authorization": "Bearer <YOUR_APIKEY>"
      }
    }
  }
}`

  return (
    <Tabs defaultValue="servers" className="flex flex-col gap-4">
      <TabsList className="w-fit">
        <TabsTrigger value="servers">{t('mcp.tab.servers')}</TabsTrigger>
        <TabsTrigger value="profiles">{t('mcp.tab.profiles')}</TabsTrigger>
        <TabsTrigger value="apikeys">{t('mcp.tab.apikeys')}</TabsTrigger>
        <TabsTrigger value="oauth">{t('mcp.tab.oauth')}</TabsTrigger>
      </TabsList>

      {/* ── Onglet MCP Servers ── */}
      <TabsContent value="servers" className="mt-0">
        <MCPBackends />
      </TabsContent>

      {/* ── Onglet Profils ── */}
      <TabsContent value="profiles" className="mt-0">
        <MCPProfiles />
      </TabsContent>

      {/* ── Onglet Client API Keys ── */}
      <TabsContent value="apikeys" className="mt-0">
        <div className="mb-4 rounded-md border bg-muted/30 p-4">
          <p className="text-xs font-semibold text-foreground">{t('mcp.desktopTitle')}</p>
          <p className="mt-1 text-xs text-muted-foreground">{t('mcp.desktopHint')}</p>
          <div className="mt-3 relative">
            <pre className="rounded-md border bg-background px-3 py-3 text-xs font-mono overflow-x-auto pr-10">
              {claudeJsonSnippet}
            </pre>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="absolute top-1.5 right-1.5 h-6 w-6 p-0"
              onClick={() => void copyText(claudeJsonSnippet)}
              title={t('mcp.copy')}
            >
              <Copy className="h-3 w-3" />
            </Button>
          </div>
        </div>
        <MCPApikeys kind="apikey" />
      </TabsContent>

      {/* ── Onglet OAuth ── */}
      <TabsContent value="oauth" className="mt-0">
        <div className="flex flex-col gap-5">
          {/* URL gateway */}
          <div className="rounded-lg border bg-muted/40 p-5">
            <div className="mb-2 flex items-center gap-2">
              <Network className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-semibold">{t('mcp.title')}</span>
            </div>
            <p className="text-sm text-muted-foreground">{t('mcp.webHint')}</p>
            <div className="mt-3 flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-background border px-2 py-1.5 text-xs font-mono">
                {gatewayUrl}
              </code>
              <Button type="button" variant="outline" size="sm" onClick={copyUrl}>
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          </div>

          {/* Procédures par client — onglets */}
          <Tabs defaultValue="claude" className="flex flex-col gap-3">
            <TabsList className="w-fit">
              <TabsTrigger value="claude">Claude</TabsTrigger>
              <TabsTrigger value="openai">OpenAI</TabsTrigger>
              <TabsTrigger value="gemini">Gemini</TabsTrigger>
              <TabsTrigger value="mistral">Mistral</TabsTrigger>
            </TabsList>

            {/* Claude */}
            <TabsContent value="claude" className="mt-0">
              <OAuthProcedure provider="claude" steps={5} gatewayUrl={gatewayUrl} copyUrl={copyUrl} settingsUrl="https://claude.ai/settings" />
            </TabsContent>

            {/* OpenAI */}
            <TabsContent value="openai" className="mt-0">
              <OAuthProcedure provider="openai" steps={4} gatewayUrl={gatewayUrl} copyUrl={copyUrl} settingsUrl="https://chatgpt.com/" />
            </TabsContent>

            {/* Gemini */}
            <TabsContent value="gemini" className="mt-0">
              <OAuthProcedure provider="gemini" steps={4} gatewayUrl={gatewayUrl} copyUrl={copyUrl} settingsUrl="https://aistudio.google.com/" />
            </TabsContent>

            {/* Mistral */}
            <TabsContent value="mistral" className="mt-0">
              <OAuthProcedure provider="mistral" steps={4} gatewayUrl={gatewayUrl} copyUrl={copyUrl} settingsUrl="https://chat.mistral.ai/" />
            </TabsContent>
          </Tabs>

          {/* Sessions OAuth actives */}
          <MCPApikeys kind="oauth" />
        </div>
      </TabsContent>
    </Tabs>
  )
}
