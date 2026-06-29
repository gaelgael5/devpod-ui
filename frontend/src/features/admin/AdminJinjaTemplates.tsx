import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import JinjaEditor from './JinjaEditor'
import { useJinjaTemplates } from './useJinjaTemplates'
import type { JinjaTemplate } from './useJinjaTemplates'

const CONTEXT_HELP_HOST = `# Variables disponibles — machine de test
host.name          # nom du host (ex: vm-abc)
host.ssh_alias     # alias SSH injecté dans le container (ex: test1)
host.ip            # adresse IP de la machine
host.ssh_user      # utilisateur SSH (ex: root)
host.ssh_port      # port SSH (ex: 22)
workspace.id       # nom du workspace
workspace.owner    # login propriétaire
user.login         # login de l'utilisateur
user.culture       # culture (fr, en…)
created_at         # horodatage ISO 8601

# Exemple
Tu disposes d'une machine de test (SSH : {{ host.ssh_alias }}).
Elle héberge Docker — tu peux y déployer des services.`

const CONTEXT_HELP_DEPLOY = `# Variables disponibles — service compose
host.name               # nom du nœud
host.ssh_alias          # alias SSH (ex: test1)
host.ip                 # IP du nœud
deployment.id           # identifiant du déploiement
deployment.ports        # liste des ports exposés (index → port)
deployment.template.name        # nom du template
deployment.template.description # description
deployment.template.version     # version
deployment.template.tags        # liste de tags
deployment.compose      # arbre YAML parsé du docker-compose
workspace.id            # nom du workspace
user.login              # login propriétaire
started_at              # horodatage ISO 8601

# Exemple Jinja2 avec boucle
Ton service {{ deployment.template.name }} est disponible.
{% for idx, port in deployment.ports.items() -%}
  Port {{ idx }} : {{ host.ip }}:{{ port }}
{% endfor %}`

function TemplateRow({ tpl, onEdit, onDelete }: {
  tpl: JinjaTemplate
  onEdit: (tpl: JinjaTemplate) => void
  onDelete: (tpl: JinjaTemplate) => void
}) {
  const { t } = useTranslation()
  return (
    <tr className="border-b last:border-0">
      <td className="py-2 pr-4 font-mono text-sm">{tpl.key}</td>
      <td className="py-2 pr-4 text-sm">{tpl.culture}</td>
      <td className="py-2 pr-4 text-xs text-muted-foreground truncate max-w-xs">
        {tpl.body.slice(0, 100)}{tpl.body.length > 100 ? '…' : ''}
      </td>
      <td className="py-2 text-right space-x-2">
        <Button size="sm" variant="outline" onClick={() => onEdit(tpl)}>
          {t('common.edit')}
        </Button>
        <Button size="sm" variant="destructive" onClick={() => onDelete(tpl)}>
          {t('common.delete')}
        </Button>
      </td>
    </tr>
  )
}

export default function AdminJinjaTemplates() {
  const { t } = useTranslation()
  const { templates, upsert, remove, preview } = useJinjaTemplates()

  const [editing, setEditing] = useState<JinjaTemplate | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [form, setForm] = useState({ key: '', culture: 'fr', body: '' })
  const [previewCtx, setPreviewCtx] = useState('')
  const [previewResult, setPreviewResult] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [contextHelp, setContextHelp] = useState<'host' | 'deploy'>('host')

  function openNew() {
    setForm({ key: '', culture: 'fr', body: '' })
    setEditing({ key: '', culture: 'fr', body: '' })
    setIsNew(true)
    setPreviewResult(null)
    setPreviewError(null)
  }

  function openEdit(tpl: JinjaTemplate) {
    setForm({ key: tpl.key, culture: tpl.culture, body: tpl.body })
    setEditing(tpl)
    setIsNew(false)
    setPreviewResult(null)
    setPreviewError(null)
  }

  function closeEditor() {
    setEditing(null)
    setPreviewResult(null)
    setPreviewError(null)
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    await upsert.mutateAsync({ key: form.key, culture: form.culture, body: form.body })
    closeEditor()
  }

  async function handleDelete(tpl: JinjaTemplate) {
    if (!confirm(t('jinjaTemplates.confirmDelete', { key: tpl.key, culture: tpl.culture }))) return
    await remove.mutateAsync({ key: tpl.key, culture: tpl.culture })
  }

  async function handlePreview() {
    setPreviewResult(null)
    setPreviewError(null)
    let ctx: unknown = {}
    if (previewCtx.trim()) {
      try {
        ctx = JSON.parse(previewCtx)
      } catch {
        setPreviewError(t('jinjaTemplates.invalidJson'))
        return
      }
    }
    try {
      const res = await preview.mutateAsync({ body: form.body, ctx })
      setPreviewResult(res.rendered)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setPreviewError(msg)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{t('jinjaTemplates.title')}</h1>
        <Button onClick={openNew}>{t('jinjaTemplates.new')}</Button>
      </div>

      {templates.isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {templates.isError && <p className="text-sm text-destructive">{t('common.error')}</p>}

      {templates.data && templates.data.length > 0 && (
        <div className="rounded-md border">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b bg-muted/30">
                <th className="py-2 pr-4 pl-3 text-xs font-medium text-muted-foreground">{t('jinjaTemplates.key')}</th>
                <th className="py-2 pr-4 text-xs font-medium text-muted-foreground">{t('jinjaTemplates.culture')}</th>
                <th className="py-2 pr-4 text-xs font-medium text-muted-foreground">{t('jinjaTemplates.preview')}</th>
                <th />
              </tr>
            </thead>
            <tbody className="pl-3">
              {templates.data.map(tpl => (
                <TemplateRow
                  key={`${tpl.key}/${tpl.culture}`}
                  tpl={tpl}
                  onEdit={openEdit}
                  onDelete={handleDelete}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {templates.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('jinjaTemplates.empty')}</p>
      )}

      {editing !== null && (
        <div className="rounded-lg border p-4 space-y-4 bg-card">
          <h2 className="font-medium">{isNew ? t('jinjaTemplates.newTitle') : t('jinjaTemplates.editTitle')}</h2>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label>{t('jinjaTemplates.key')}</Label>
                <Input
                  value={form.key}
                  onChange={e => setForm(f => ({ ...f, key: e.target.value }))}
                  disabled={!isNew}
                  placeholder="ex: test_host_available"
                  required
                />
              </div>
              <div className="space-y-1">
                <Label>{t('jinjaTemplates.culture')}</Label>
                <Select
                  value={form.culture}
                  onValueChange={v => setForm(f => ({ ...f, culture: v }))}
                  disabled={!isNew}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="fr">fr</SelectItem>
                    <SelectItem value="en">en</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between mb-1">
                <Label>{t('jinjaTemplates.body')}</Label>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant={contextHelp === 'host' ? 'default' : 'outline'}
                    onClick={() => setContextHelp('host')}
                  >
                    {t('jinjaTemplates.helpHost')}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={contextHelp === 'deploy' ? 'default' : 'outline'}
                    onClick={() => setContextHelp('deploy')}
                  >
                    {t('jinjaTemplates.helpDeploy')}
                  </Button>
                </div>
              </div>
              <JinjaEditor
                value={form.body}
                onChange={v => setForm(f => ({ ...f, body: v }))}
                minHeight="200px"
              />
            </div>

            <details className="text-xs rounded-md border">
              <summary className="cursor-pointer px-3 py-2 font-medium text-muted-foreground">
                {t('jinjaTemplates.contextHelp')}
              </summary>
              <pre className="px-3 py-2 overflow-auto text-muted-foreground whitespace-pre-wrap">
                {contextHelp === 'host' ? CONTEXT_HELP_HOST : CONTEXT_HELP_DEPLOY}
              </pre>
            </details>

            <div className="space-y-2">
              <Label>{t('jinjaTemplates.previewCtx')}</Label>
              <textarea
                className="w-full h-24 rounded-md border border-input bg-background px-3 py-2 text-sm font-mono resize-y"
                placeholder='{"host": {"ssh_alias": "test1", "ip": "192.168.1.10", ...}}'
                value={previewCtx}
                onChange={e => setPreviewCtx(e.target.value)}
              />
              <Button type="button" size="sm" variant="outline" onClick={handlePreview} disabled={preview.isPending}>
                {t('jinjaTemplates.previewBtn')}
              </Button>
              {previewError && (
                <pre className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive whitespace-pre-wrap">
                  {previewError}
                </pre>
              )}
              {previewResult !== null && (
                <pre className="rounded-md border bg-muted/30 px-3 py-2 text-sm whitespace-pre-wrap">
                  {previewResult}
                </pre>
              )}
            </div>

            <div className="flex gap-2">
              <Button type="submit" disabled={upsert.isPending}>
                {t('common.save')}
              </Button>
              <Button type="button" variant="outline" onClick={closeEditor}>
                {t('common.cancel')}
              </Button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
