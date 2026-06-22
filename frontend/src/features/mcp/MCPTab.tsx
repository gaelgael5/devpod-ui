import { useTranslation } from 'react-i18next'
import { Network } from 'lucide-react'
import MCPBackends from './MCPBackends'
import MCPApikeys from './MCPApikeys'

export default function MCPTab() {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border bg-muted/40 p-5">
        <div className="mb-2 flex items-center gap-2">
          <Network className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{t('mcp.title')}</span>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">{t('mcp.info')}</p>
      </div>
      <MCPBackends />
      <MCPApikeys />
    </div>
  )
}
