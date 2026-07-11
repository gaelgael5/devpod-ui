import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Compass } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

/**
 * Bloc « MCP Explore » — explore un serveur MCP qui expose des services, avant de
 * l'enregistrer dans « MCP Servers ». Squelette : le champ URL et le bouton sont
 * en place ; la logique d'exploration sera branchée à la spec suivante.
 */
export default function MCPExplore() {
  const { t } = useTranslation()
  const [url, setUrl] = useState('')

  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-muted/40 p-5">
      <div className="flex items-center gap-2">
        <Compass className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold">{t('mcp.explore.title')}</h2>
      </div>
      <p className="text-sm text-muted-foreground">{t('mcp.explore.subtitle')}</p>
      <div className="flex items-center gap-2">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t('mcp.explore.urlPlaceholder')}
          className="h-9"
        />
        <Button size="sm" disabled={!url.trim()}>
          {t('mcp.explore.exploreButton')}
        </Button>
      </div>
    </div>
  )
}
