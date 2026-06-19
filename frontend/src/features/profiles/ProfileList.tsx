import { useState } from 'react'
import { Link } from 'react-router-dom'
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
import { useProfiles, useDeleteProfile, useDeleteSharedProfile, useForkProfile } from './hooks/useProfiles'
import type { ProfileSummary } from './api/profiles'

export default function ProfileList() {
  const { t } = useTranslation()
  const { data: profiles, isLoading, isError } = useProfiles()
  const deleteMutation = useDeleteProfile()
  const deleteSharedMutation = useDeleteSharedProfile()
  const forkMutation = useForkProfile()
  const [confirmDelete, setConfirmDelete] = useState<ProfileSummary | null>(null)

  const mine = profiles?.filter((p: ProfileSummary) => p.scope === 'user') ?? []
  const shared = profiles?.filter((p: ProfileSummary) => p.scope === 'shared') ?? []

  function handleDeleteConfirm() {
    if (!confirmDelete) return
    const onSuccess = () => setConfirmDelete(null)
    if (confirmDelete.scope === 'shared') {
      deleteSharedMutation.mutate(confirmDelete.slug, { onSuccess })
    } else {
      deleteMutation.mutate(confirmDelete.slug, { onSuccess })
    }
  }

  if (isLoading) return <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
  if (isError) return <p className="text-sm text-destructive">{t('profiles.errors.load')}</p>

  return (
    <div className="flex flex-col gap-8 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('profiles.title')}</h1>
        <Button asChild size="sm">
          <Link to="/profiles/new">
            <Plus className="mr-1 h-4 w-4" />
            {t('profiles.new')}
          </Link>
        </Button>
      </div>

      {/* Mes profils */}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-medium">{t('profiles.sections.mine')}</h2>
        {mine.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('profiles.empty.mine')}</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {mine.map((p: ProfileSummary) => (
              <ProfileCard
                key={p.slug}
                profile={p}
                onDelete={() => setConfirmDelete(p)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Profils partagés */}
      {shared.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-medium">{t('profiles.sections.shared')}</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {shared.map((p: ProfileSummary) => (
              <ProfileCard
                key={p.slug}
                profile={p}
                onFork={() => forkMutation.mutate(p.slug)}
                forking={forkMutation.isPending && forkMutation.variables === p.slug}
                onDelete={p.editable && !p.gallery_source ? () => setConfirmDelete(p) : undefined}
              />
            ))}
          </div>
        </section>
      )}

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
              onClick={handleDeleteConfirm}
              disabled={deleteMutation.isPending || deleteSharedMutation.isPending}
            >
              {t('profiles.delete.confirm_btn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

interface CardProps {
  profile: ProfileSummary
  onDelete?: () => void
  onFork?: () => void
  forking?: boolean
}

function ProfileCard({ profile, onDelete, onFork, forking }: CardProps) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-medium">{profile.name}</p>
          <p className="text-xs text-muted-foreground">
            {profile.extension_count} extension{profile.extension_count !== 1 ? 's' : ''}
          </p>
        </div>
      </div>
      {profile.description && (
        <p className="line-clamp-2 text-sm text-muted-foreground">{profile.description}</p>
      )}
      <div className="mt-auto flex gap-2 pt-2">
        {profile.scope === 'user' && profile.editable && (
          <Button size="sm" variant="outline" asChild>
            <Link to={`/profiles/${profile.slug}`}>{t('workspaces.actions.edit')}</Link>
          </Button>
        )}
        {onFork && (
          <Button size="sm" variant="outline" onClick={onFork} disabled={forking}>
            {t('profiles.fork')}
          </Button>
        )}
        {onDelete && (
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={onDelete}
          >
            {t('workspaces.actions.delete')}
          </Button>
        )}
      </div>
    </div>
  )
}
