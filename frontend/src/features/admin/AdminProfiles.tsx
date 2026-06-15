import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useProfiles, useSaveSharedProfile, useDeleteSharedProfile } from '@/features/profiles/hooks/useProfiles'
import type { ProfileSummary } from '@/features/profiles/api/profiles'

interface FormState {
  name: string
  description: string
  extensions: string
}

const EMPTY: FormState = { name: '', description: '', extensions: '' }

export default function AdminProfiles() {
  const { t } = useTranslation()
  const { data: profiles, isLoading, isError } = useProfiles()
  const saveMutation = useSaveSharedProfile()
  const deleteMutation = useDeleteSharedProfile()

  const [editingSlug, setEditingSlug] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [confirmDelete, setConfirmDelete] = useState<ProfileSummary | null>(null)

  const shared = profiles?.filter((p) => p.scope === 'shared') ?? []
  const isEditing = editingSlug !== null

  function openCreate() {
    setEditingSlug(null)
    setForm(EMPTY)
    setOpen(true)
  }

  function openEdit(p: ProfileSummary) {
    setEditingSlug(p.slug)
    setForm({ name: p.name, description: p.description, extensions: '' })
    setOpen(true)
  }

  function handleClose() {
    setOpen(false)
    setEditingSlug(null)
    setForm(EMPTY)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const exts = form.extensions
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    const body = { name: form.name, description: form.description, extensions: exts, settings: {} }
    saveMutation.mutate(
      { slug: editingSlug ?? undefined, body },
      { onSuccess: handleClose },
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('admin.sharedProfiles')}</h2>
        <Button size="sm" onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" />
          {t('admin.addProfile')}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && shared.length === 0 && (
        <p className="text-muted-foreground">{t('admin.profilesEmpty')}</p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {shared.map((p) => (
          <div key={p.slug} className="rounded-lg border bg-card p-4">
            <div className="mb-1 font-medium">{p.name}</div>
            <div className="mb-3 text-xs text-muted-foreground">
              {p.extension_count} extension{p.extension_count !== 1 ? 's' : ''}
            </div>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => openEdit(p)}>
                {t('workspaces.actions.edit')}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive hover:text-destructive"
                onClick={() => setConfirmDelete(p)}
              >
                {t('workspaces.actions.delete')}
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* Dialog create/edit */}
      <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
        <DialogContent>
          <form onSubmit={handleSubmit}>
            <DialogHeader>
              <DialogTitle>{isEditing ? t('admin.editProfile') : t('admin.addProfile')}</DialogTitle>
              <DialogDescription className="sr-only">
                {isEditing ? t('admin.editProfile') : t('admin.addProfile')}
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3 py-4">
              <Label htmlFor="ap-name">{t('profiles.fields.name')}</Label>
              <Input
                id="ap-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
              <Label htmlFor="ap-desc">{t('profiles.fields.description')}</Label>
              <Input
                id="ap-desc"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
              <Label htmlFor="ap-ext">{t('admin.extensionsHint')}</Label>
              <textarea
                id="ap-ext"
                className="min-h-[80px] w-full rounded-md border bg-background px-3 py-2 text-sm font-mono"
                value={form.extensions}
                onChange={(e) => setForm((f) => ({ ...f, extensions: e.target.value }))}
                placeholder="esbenp.prettier-vscode&#10;dbaeumer.vscode-eslint"
              />
            </div>
            <DialogFooter>
              <Button variant="ghost" type="button" onClick={handleClose}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={!form.name.trim() || saveMutation.isPending}>
                {t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Dialog confirmation suppression */}
      <Dialog open={Boolean(confirmDelete)} onOpenChange={(o) => !o && setConfirmDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('profiles.delete.confirm')}</DialogTitle>
            <DialogDescription>
              {t('profiles.delete.description', { name: confirmDelete?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
              {t('profiles.delete.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (confirmDelete) {
                  deleteMutation.mutate(confirmDelete.slug, {
                    onSuccess: () => setConfirmDelete(null),
                  })
                }
              }}
              disabled={deleteMutation.isPending}
            >
              {t('profiles.delete.confirm_btn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
