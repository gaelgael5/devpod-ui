import { useTranslation } from 'react-i18next'
import { Network, Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import MCPBackends from './MCPBackends'
import MCPApikeys from './MCPApikeys'

export default function MCPTab() {
  const { t } = useTranslation()
  const gatewayUrl = `${window.location.origin}/mcp`

  async function copyUrl() {
    await navigator.clipboard.writeText(gatewayUrl)
    toast.success(t('mcp.gatewayUrlCopied'))
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border bg-muted/40 p-5">
        <div className="mb-2 flex items-center gap-2">
          <Network className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{t('mcp.title')}</span>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">{t('mcp.info')}</p>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          {/* Claude web → OAuth : rien à créer ici, juste l'URL à coller. */}
          <div className="flex-1 rounded-md border bg-background p-3">
            <p className="text-xs font-semibold text-foreground">{t('mcp.webTitle')}</p>
            <p className="mt-1 text-xs text-muted-foreground">{t('mcp.webHint')}</p>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-muted px-2 py-1 text-xs">
                {gatewayUrl}
              </code>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={copyUrl}
                title={t('mcp.copy')}
              >
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          </div>
          {/* Claude Desktop / scripts → apikey statique émise ci-dessous. */}
          <div className="flex-1 rounded-md border bg-background p-3">
            <p className="text-xs font-semibold text-foreground">{t('mcp.desktopTitle')}</p>
            <p className="mt-1 text-xs text-muted-foreground">{t('mcp.desktopHint')}</p>
          </div>
        </div>
      </div>
      <MCPBackends />
      <MCPApikeys />
    </div>
  )
}
