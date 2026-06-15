import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useProfiles, useDeleteSharedProfile } from '@/features/profiles/hooks/useProfiles'
import type { ProfileSummary } from '@/features/profiles/api/profiles'

export default function AdminProfiles() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { data: profiles, isLoading, isError } = useProfiles()
  const deleteMutation = useDeleteSharedProfile()

  const [confirmDelete, setConfirmDelete] = useState<ProfileSummary | null>(null)

  const shared = profiles?.filter((p) => p.scope === 'shared') ?? []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('admin.sharedProfiles')}</h2>
        <Button size="sm" onClick={() => navigate('/admin/profiles/new')}>
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
              <Button
                size="sm"
                variant="ghost"
                onClick={() => navigate(`/admin/profiles/${p.slug}`)}
              >
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
