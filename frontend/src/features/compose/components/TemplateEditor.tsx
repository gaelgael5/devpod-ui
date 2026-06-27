import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import YamlEditor from './YamlEditor'
import ParameterRows from './ParameterRows'
import { useSaveTemplate } from '../hooks/useCompose'
import type { ComposeParam, ComposeTemplate, TemplateBody } from '../api/types'

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,40}[a-z0-9]$/

interface TemplateEditorProps {
  template?: ComposeTemplate
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function TemplateEditor({ template, open, onOpenChange }: TemplateEditorProps) {
  const { t } = useTranslation()
  const isCreate = !template
  const save = useSaveTemplate()

  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState('')
  const [version, setVersion] = useState('1.0.0')
  const [composeContent, setComposeContent] = useState('services: {}\n')
  const [parameters, setParameters] = useState<ComposeParam[]>([])
  const [serverError, setServerError] = useState<string | null>(null)
  const [idError, setIdError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    if (template) {
      setId(template.id)
      setName(template.name)
      setDescription(template.description)
      setTags(template.tags.join(', '))
      setVersion(template.version)
      setComposeContent(template.compose_content)
      setParameters(template.parameters)
    } else {
      setId('')
      setName('')
      setDescription('')
      setTags('')
      setVersion('1.0.0')
      setComposeContent('services: {}\n')
      setParameters([])
    }
    setServerError(null)
    setIdError(null)
  }, [open, template])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (isCreate && !SLUG_RE.test(id)) {
      setIdError(t('compose.form.idHint'))
      return
    }
    const body: TemplateBody = {
      name,
      description,
      tags: tags.split(',').map((s) => s.trim()).filter(Boolean),
      version,
      compose_content: composeContent,
      parameters,
      source: 'user',
    }
    try {
      const result = await save.mutateAsync({
        id: isCreate ? id : template!.id,
        body,
        create: isCreate,
      })
      if (result.warnings.length > 0) {
        result.warnings.forEach((w) => toast.warning(w))
      }
      onOpenChange(false)
    } catch (err) {
      setServerError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isCreate ? t('compose.admin.new') : t('compose.admin.edit')}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          {isCreate && (
            <div>
              <Label htmlFor="tpl-id">{t('compose.form.id')}</Label>
              <Input
                id="tpl-id"
                value={id}
                onChange={(e) => { setId(e.target.value); setIdError(null) }}
                placeholder="my-template"
                required
              />
              {idError && <p className="mt-1 text-xs text-destructive">{idError}</p>}
              <p className="mt-1 text-xs text-muted-foreground">{t('compose.form.idHint')}</p>
            </div>
          )}
          <div>
            <Label htmlFor="tpl-name">{t('compose.form.name')}</Label>
            <Input
              id="tpl-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="tpl-desc">{t('compose.form.description')}</Label>
            <Input
              id="tpl-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="tpl-tags">{t('compose.form.tags')}</Label>
              <Input
                id="tpl-tags"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="web, docker"
              />
            </div>
            <div>
              <Label htmlFor="tpl-version">{t('compose.form.version')}</Label>
              <Input
                id="tpl-version"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                required
              />
            </div>
          </div>
          <div>
            <Label>{t('compose.form.yaml')}</Label>
            <YamlEditor value={composeContent} onChange={setComposeContent} minHeight="200px" />
          </div>
          <ParameterRows params={parameters} onChange={setParameters} />
          {serverError && (
            <Alert variant="destructive">
              <AlertDescription>{serverError}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
