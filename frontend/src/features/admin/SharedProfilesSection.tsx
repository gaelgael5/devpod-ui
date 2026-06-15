import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
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
import {
  useProfiles,
  useProfile,
  useSaveSharedProfile,
  useDeleteSharedProfile,
} from '@/features/profiles/hooks/useProfiles'
import type { ProfileSummary } from '@/features/profiles/api/profiles'

interface FormState {
  name: string
  description: string
  extensions: string
  settings: string
}

const EMPTY: FormState = { name: '', description: '', extensions: '', settings: '{}' }

export default function SharedProfilesSection() {
  const { t } = useTranslation()
  const { data: allProfiles, isLoading, isError } = useProfiles()
  const saveMutation = useSaveSharedProfile()
  const deleteMutation = useDeleteSharedProfile()

  const [editingSlug, setEditingSlug] = useState<string | null>(null)
  const [openEdit, setOpenEdit] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [settingsError, setSettingsError] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<ProfileSummary | null>(null)

  const { data: editingProfile } = useProfile('shared', editingSlug ?? undefined)
  const shared = allProfiles?.filter((p) => p.scope === 'shared') ?? []

  useEffect(() => {
    if (!editingProfile || editingProfile.slug !== editingSlug) return
    setForm({
      name: editingProfile.name,
      description: editingProfile.description,
      extensions: editingProfile.extensions.join('\n'),
      settings: JSON.stringify(editingProfile.settings ?? {}, null, 2),
    })
  }, [editingProfile, editingSlug])

  function handleEditOpen(p: ProfileSummary) {
    setEditingSlug(p.slug)
    setForm({ ...EMPTY, name: p.name, description: p.description })
    setSettingsError(false)
    setOpenEdit(true)
  }

  function handleEditClose() {
    setOpenEdit(false)
    setEditingSlug(null)
    setForm(EMPTY)
    setSettingsError(false)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    let settings: Record<string, unknown> = {}
    try {
      settings = JSON.parse(form.settings || '{}')
      setSettingsError(false)
    } catch {
      setSettingsError(true)
      return
    }
    const extensions = form.extensions.split('\n').map((s) => s.trim()).filter(Boolean)
    saveMutation.mutate(
      {
        slug: editingSlug!,
        body: { name: form.name, description: form.description, extensions, settings },
      },
      { onSuccess: handleEditClose },
    )
  }

  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">
        {t('admin.profileSources.localProfiles')}
      </h2>
      {isLoading && (
        <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
      )}
      {isError && (
        <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>
      )}
      {!isLoading && !isError && shared.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {t('admin.profileSources.localEmpty')}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {shared.map((p) => (
          <div key={p.slug} className="rounded-lg border bg-card p-4">
            <div className="mb-1 font-medium">{p.name}</div>
            <div className="mb-1 text-sm text-muted-foreground">{p.description}</div>
            <div className="mb-3 text-xs text-muted-foreground">
              {p.extension_count} extension{p.extension_count !== 1 ? 's' : ''}
            </div>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => handleEditOpen(p)}>
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

      {/* Dialog édition */}
      <Dialog open={openEdit} onOpenChange={(o) => !o && handleEditClose()}>
        <DialogContent>
          <form onSubmit={handleSubmit}>
            <DialogHeader>
              <DialogTitle>{t('admin.editProfile')}</DialogTitle>
              <DialogDescription className="sr-only">
                {t('admin.editProfile')}
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3 py-4">
              <Label htmlFor="sp-name">{t('profiles.fields.name')}</Label>
              <Input
                id="sp-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
              <Label htmlFor="sp-desc">{t('profiles.fields.description')}</Label>
              <Input
                id="sp-desc"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
              <Label htmlFor="sp-ext">{t('admin.extensionsHint')}</Label>
              <textarea
                id="sp-ext"
                className="min-h-[80px] w-full rounded-md border bg-background px-3 py-2 text-sm font-mono"
                value={form.extensions}
                onChange={(e) => setForm((f) => ({ ...f, extensions: e.target.value }))}
                placeholder="esbenp.prettier-vscode&#10;dbaeumer.vscode-eslint"
              />
              <Label htmlFor="sp-settings">{t('admin.settingsHint')}</Label>
              <textarea
                id="sp-settings"
                className={`min-h-[100px] w-full rounded-md border bg-background px-3 py-2 text-sm font-mono${
                  settingsError ? ' border-destructive' : ''
                }`}
                value={form.settings}
                onChange={(e) => {
                  setForm((f) => ({ ...f, settings: e.target.value }))
                  setSettingsError(false)
                }}
                placeholder="{}"
              />
              {settingsError && (
                <p className="text-xs text-destructive">{t('admin.settingsInvalid')}</p>
              )}
            </div>
            <DialogFooter>
              <Button variant="ghost" type="button" onClick={handleEditClose}>
                {t('common.cancel')}
              </Button>
              <Button
                type="submit"
                disabled={!form.name.trim() || saveMutation.isPending}
              >
                {t('common.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Dialog confirmation suppression */}
      <Dialog
        open={Boolean(confirmDelete)}
        onOpenChange={(o) => !o && setConfirmDelete(null)}
      >
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
    </section>
  )
}
