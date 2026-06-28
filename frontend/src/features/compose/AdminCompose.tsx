import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, Trash2, RefreshCw, Search } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useDeleteTemplate, useTemplates } from './hooks/useCompose'
import { useComposeSources, type RemoteComposeTemplate } from './hooks/useComposeSources'
import TemplateEditor from './components/TemplateEditor'
import type { ComposeTemplate } from './api/types'

export default function AdminCompose() {
  const { t } = useTranslation()
  const { data: templates = [], isLoading } = useTemplates()
  const deleteMutation = useDeleteTemplate()
  const { sourcesQuery, updateSources, previewQuery, importTemplate } = useComposeSources()

  const [editorOpen, setEditorOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<ComposeTemplate | undefined>()
  const [confirmDelete, setConfirmDelete] = useState<ComposeTemplate | null>(null)
  const [newSourceUrl, setNewSourceUrl] = useState('')
  const [galleryFilter, setGalleryFilter] = useState('')

  const { data: sourcesData } = sourcesQuery
  const { data: previewData, isFetching: isLoadingGallery, refetch: refetchGallery } = previewQuery

  const sources = sourcesData?.sources ?? []
  const galleryTemplates = previewData?.templates ?? []

  const filteredGallery = useMemo(() => {
    const q = galleryFilter.trim().toLowerCase()
    if (!q) return galleryTemplates
    return galleryTemplates.filter((tpl: RemoteComposeTemplate) =>
      tpl.name.toLowerCase().includes(q) ||
      tpl.id.toLowerCase().includes(q) ||
      tpl.image.toLowerCase().includes(q) ||
      tpl.tags.some((tag) => tag.toLowerCase().includes(q)),
    )
  }, [galleryTemplates, galleryFilter])

  function openNew() {
    setEditTarget(undefined)
    setEditorOpen(true)
  }

  function openEdit(tpl: ComposeTemplate) {
    setEditTarget(tpl)
    setEditorOpen(true)
  }

  function handleDeleteConfirm() {
    if (!confirmDelete) return
    deleteMutation.mutate(confirmDelete.id, { onSuccess: () => setConfirmDelete(null) })
  }

  function addSource() {
    const url = newSourceUrl.trim()
    if (!url) return
    updateSources.mutate([...sources, url])
    setNewSourceUrl('')
  }

  function removeSource(idx: number) {
    updateSources.mutate(sources.filter((_, i) => i !== idx))
  }

  return (
    <div className="flex flex-col gap-10 p-6">

      {/* ── Sources ────────────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t('compose.catalog.sources')}</h2>
        <div className="flex flex-col gap-2">
          {sources.map((url, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <Input value={url} readOnly className="flex-1 font-mono text-xs opacity-80" />
              <Button
                size="icon"
                variant="ghost"
                onClick={() => removeSource(idx)}
                aria-label={t('compose.catalog.deleteSource')}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Input
              value={newSourceUrl}
              onChange={(e) => setNewSourceUrl(e.target.value)}
              placeholder="https://raw.githubusercontent.com/…/toc.txt"
              className="flex-1 font-mono text-xs"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addSource()
                }
              }}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={addSource}
              disabled={!newSourceUrl.trim() || updateSources.isPending}
            >
              <Plus className="h-4 w-4 mr-1" />
              {t('compose.catalog.addSource')}
            </Button>
          </div>
        </div>
      </section>

      {/* ── Galerie ────────────────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t('compose.catalog.gallery')}</h2>
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetchGallery()}
            disabled={isLoadingGallery}
          >
            <RefreshCw className={`h-4 w-4 mr-1 ${isLoadingGallery ? 'animate-spin' : ''}`} />
            {t('compose.catalog.refresh')}
          </Button>
        </div>

        {galleryTemplates.length > 0 && (
          <div className="relative mb-4">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={t('compose.catalog.filter')}
              value={galleryFilter}
              onChange={(e) => setGalleryFilter(e.target.value)}
              className="pl-8 text-sm"
            />
          </div>
        )}

        {isLoadingGallery && <p className="text-sm text-muted-foreground">…</p>}
        {!isLoadingGallery && !previewData && (
          <p className="text-sm text-muted-foreground">{t('compose.catalog.hint')}</p>
        )}
        {!isLoadingGallery && previewData && galleryTemplates.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('compose.catalog.empty')}</p>
        )}
        {!isLoadingGallery && galleryTemplates.length > 0 && filteredGallery.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('compose.catalog.noMatch')}</p>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredGallery.map((tpl: RemoteComposeTemplate) => (
            <div key={tpl.source_url} className="rounded-lg border bg-card p-4">
              <div className="mb-2 flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{tpl.name}</div>
                  <div className="text-xs text-muted-foreground font-mono">{tpl.id}</div>
                </div>
                <Button
                  size="sm"
                  onClick={() => importTemplate.mutate(tpl.source_url)}
                  disabled={importTemplate.isPending}
                >
                  {importTemplate.isPending
                    ? t('compose.catalog.importing')
                    : t('compose.catalog.import')}
                </Button>
              </div>
              {tpl.description && (
                <p className="text-sm text-muted-foreground line-clamp-2 mb-2">
                  {tpl.description}
                </p>
              )}
              {tpl.image && (
                <p className="text-xs text-muted-foreground font-mono mb-2">{tpl.image}</p>
              )}
              {tpl.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {tpl.tags.map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                </div>
              )}
              <div className="mt-2 text-xs text-muted-foreground">v{tpl.version}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Templates locaux ────────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t('compose.admin.title')}</h2>
          <Button size="sm" onClick={openNew}>
            <Plus className="mr-1 h-4 w-4" />
            {t('compose.admin.new')}
          </Button>
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
        {!isLoading && templates.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('compose.empty.templates')}</p>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {templates.map((tpl) => (
            <TemplateCard
              key={tpl.id}
              template={tpl}
              onEdit={() => openEdit(tpl)}
              onDelete={() => setConfirmDelete(tpl)}
            />
          ))}
        </div>
      </section>

      <TemplateEditor
        template={editTarget}
        open={editorOpen}
        onOpenChange={(o) => {
          setEditorOpen(o)
          if (!o) setEditTarget(undefined)
        }}
      />

      <Dialog open={Boolean(confirmDelete)} onOpenChange={(o) => !o && setConfirmDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('compose.delete.title')}</DialogTitle>
            <DialogDescription>
              {t('compose.delete.description', { name: confirmDelete?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
              {t('compose.delete.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteMutation.isPending}
            >
              {t('compose.delete.ok')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

interface CardProps {
  template: ComposeTemplate
  onEdit: () => void
  onDelete: () => void
}

function TemplateCard({ template, onEdit, onDelete }: CardProps) {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader>
        <CardTitle>{template.name}</CardTitle>
        <CardDescription>
          v{template.version} · {template.source}
        </CardDescription>
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
      <CardFooter className="gap-2">
        <Button size="sm" variant="outline" onClick={onEdit}>
          <Pencil className="mr-1 h-3 w-3" />
          {t('compose.actions.edit')}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-destructive hover:text-destructive"
          onClick={onDelete}
        >
          <Trash2 className="mr-1 h-3 w-3" />
          {t('compose.actions.delete')}
        </Button>
      </CardFooter>
    </Card>
  )
}
