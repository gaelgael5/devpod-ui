import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useSetAutoStart, useTemplates } from './hooks/useCompose'
import type { ComposeTemplate } from './api/types'
import AutoStartDialog from './components/AutoStartDialog'
import DeployDialog from './components/DeployDialog'
import DeploymentsPanel from './components/DeploymentsPanel'

interface TemplateCardProps {
  template: ComposeTemplate
  onDeploy: () => void
  onAutoStartChange: (enabled: boolean) => void
}

function TemplateCard({ template, onDeploy, onAutoStartChange }: TemplateCardProps) {
  const { t } = useTranslation()
  const autoStartId = `auto-start-${template.id}`
  return (
    <Card>
      <CardHeader>
        <CardTitle>{template.name}</CardTitle>
        <CardDescription>v{template.version}</CardDescription>
      </CardHeader>
      <CardContent>
        {template.description && (
          <p className="text-sm text-muted-foreground line-clamp-2">{template.description}</p>
        )}
        {template.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {template.tags.map((tag) => (
              <Badge key={tag} variant="secondary">
                {tag}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-3">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor={autoStartId} className="text-sm font-normal text-muted-foreground">
            {t('compose.autoStart.label')}
          </Label>
          <Switch
            id={autoStartId}
            checked={template.auto_start}
            onCheckedChange={onAutoStartChange}
          />
        </div>
        <Button size="sm" onClick={onDeploy}>
          {t('compose.deploy')}
        </Button>
      </CardFooter>
    </Card>
  )
}

export default function ComposeGallery() {
  const { t } = useTranslation()
  const { data: templates = [], isLoading } = useTemplates()
  const setAutoStart = useSetAutoStart()
  const [deployTarget, setDeployTarget] = useState<ComposeTemplate | null>(null)
  const [autoStartTarget, setAutoStartTarget] = useState<ComposeTemplate | null>(null)

  function handleAutoStartChange(template: ComposeTemplate, enabled: boolean) {
    if (!enabled) {
      setAutoStart.mutate({ id: template.id, body: { enabled: false } })
      return
    }
    const missingRequired = template.parameters.some((p) => p.required && !p.default?.trim())
    if (missingRequired) {
      setAutoStartTarget(template)
      return
    }
    setAutoStart.mutate({ id: template.id, body: { enabled: true, env_values: {} } })
  }

  return (
    <div className="p-6" data-testid="compose-gallery">
      <h1 className="text-2xl font-semibold mb-4">{t('compose.title')}</h1>
      <Tabs defaultValue="gallery">
        <TabsList>
          <TabsTrigger value="gallery">{t('compose.gallery')}</TabsTrigger>
          <TabsTrigger value="deployments">{t('compose.deployments')}</TabsTrigger>
        </TabsList>
        <TabsContent value="gallery">
          {isLoading && (
            <p className="text-sm text-muted-foreground mt-4">{t('common.loading')}</p>
          )}
          {!isLoading && templates.length === 0 && (
            <p className="text-sm text-muted-foreground mt-4">{t('compose.empty.templates')}</p>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mt-4">
            {templates.map((tpl) => (
              <TemplateCard
                key={tpl.id}
                template={tpl}
                onDeploy={() => setDeployTarget(tpl)}
                onAutoStartChange={(enabled) => handleAutoStartChange(tpl, enabled)}
              />
            ))}
          </div>
        </TabsContent>
        <TabsContent value="deployments">
          <DeploymentsPanel />
        </TabsContent>
      </Tabs>

      {deployTarget && (
        <DeployDialog
          template={deployTarget}
          open={true}
          onOpenChange={(o) => {
            if (!o) setDeployTarget(null)
          }}
        />
      )}

      {autoStartTarget && (
        <AutoStartDialog
          template={autoStartTarget}
          open={true}
          onOpenChange={(o) => {
            if (!o) setAutoStartTarget(null)
          }}
        />
      )}
    </div>
  )
}
