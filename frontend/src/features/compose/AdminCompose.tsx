import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import TemplateEditor from './components/TemplateEditor'
import type { ComposeTemplate } from './api/types'

export default function AdminCompose() {
  const { t } = useTranslation()
  const { data: templates = [], isLoading } = useTemplates()
  const deleteMutation = useDeleteTemplate()

  const [editorOpen, setEditorOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<ComposeTemplate | undefined>()
  const [confirmDelete, setConfirmDelete] = useState<ComposeTemplate | null>(null)

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

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('compose.admin.title')}</h1>
        <Button size="sm" onClick={openNew}>
          <Plus className="mr-1 h-4 w-4" />
          {t('compose.admin.new')}
        </Button>
      </div>

      {isLoading && (
        <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
      )}
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
              <Badge key={tag} variant="secondary">{tag}</Badge>
            ))}
          </div>
        )}
      </CardContent>
      <CardFooter className="gap-2">
        <Button size="sm" variant="outline" onClick={onEdit}>
          <Pencil className="mr-1 h-3 w-3" />
          {t('workspaces.actions.edit')}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-destructive hover:text-destructive"
          onClick={onDelete}
        >
          <Trash2 className="mr-1 h-3 w-3" />
          {t('workspaces.actions.delete')}
        </Button>
      </CardFooter>
    </Card>
  )
}
