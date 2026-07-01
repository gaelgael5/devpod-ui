import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, RefreshCw, Search, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useProfileSources, type RemoteProfile } from './useProfileSources'
import { useProfiles, useDeleteSharedProfile } from '@/features/profiles/hooks/useProfiles'

export default function AdminProfileSources() {
  const { t } = useTranslation()
  const { sourcesQuery, updateSources, previewQuery, importProfile } = useProfileSources()
  const { data: sourcesData } = sourcesQuery
  const {
    data: previewData,
    isFetching: isLoadingGallery,
    refetch: refetchGallery,
  } = previewQuery

  const { data: localProfiles } = useProfiles()
  const deleteSharedMutation = useDeleteSharedProfile()

  const [newSourceUrl, setNewSourceUrl] = useState('')
  const [galleryFilter, setGalleryFilter] = useState('')
  const [confirmRemove, setConfirmRemove] = useState<RemoteProfile | null>(null)

  const sources = sourcesData?.sources ?? []
  const galleryProfiles = previewData?.profiles ?? []

  const importedSlugs = useMemo(() => {
    const shared = (localProfiles ?? []).filter(p => p.scope === 'shared')
    return new Set(shared.map(p => p.slug))
  }, [localProfiles])

  const filteredProfiles = useMemo(() => {
    const q = galleryFilter.trim().toLowerCase()
    if (!q) return galleryProfiles
    return galleryProfiles.filter(
      (p: RemoteProfile) =>
        p.name?.toLowerCase().includes(q) ||
        p.description?.toLowerCase().includes(q)
    )
  }, [galleryProfiles, galleryFilter])

  function addSource() {
    const url = newSourceUrl.trim()
    if (!url) return
    updateSources.mutate([...sources, url])
    setNewSourceUrl('')
  }

  function removeSource(idx: number) {
    updateSources.mutate(sources.filter((_, i) => i !== idx))
  }

  function slugify(name: string): string {
    const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
    return slug || 'profil'
  }

  function isImported(p: RemoteProfile): boolean {
    return importedSlugs.has(slugify(p.name))
  }

  function handleRemoveConfirm() {
    if (!confirmRemove) return
    deleteSharedMutation.mutate(slugify(confirmRemove.name), {
      onSuccess: () => setConfirmRemove(null),
    })
  }

  return (
    <div className="flex flex-col gap-10">

      {/* ── Sources ─────────────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-lg font-semibold">
          {t('admin.profileSources.sources')}
        </h2>
        <div className="flex flex-col gap-2">
          {sources.map((url, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <Input
                value={url}
                readOnly
                className="flex-1 font-mono text-xs opacity-80"
              />
              <Button
                size="icon"
                variant="ghost"
                onClick={() => removeSource(idx)}
                aria-label={t('admin.deleteSource')}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Input
              value={newSourceUrl}
              onChange={(e) => setNewSourceUrl(e.target.value)}
              placeholder="https://raw.githubusercontent.com/…/profiles/toc.txt"
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
              {t('admin.addSource')}
            </Button>
          </div>
        </div>
      </section>

      {/* ── Galerie ─────────────────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {t('admin.profileSources.gallery')}
          </h2>
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetchGallery()}
            disabled={isLoadingGallery}
          >
            <RefreshCw
              className={`h-4 w-4 mr-1 ${isLoadingGallery ? 'animate-spin' : ''}`}
            />
            {t('admin.refreshGallery')}
          </Button>
        </div>
        {galleryProfiles.length > 0 && (
          <div className="relative mb-4">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={t('admin.profileSources.filter')}
              value={galleryFilter}
              onChange={(e) => setGalleryFilter(e.target.value)}
              className="pl-8 text-sm"
            />
          </div>
        )}
        {isLoadingGallery && (
          <p className="text-sm text-muted-foreground">…</p>
        )}
        {!isLoadingGallery && galleryProfiles.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t('admin.profileSources.empty')}
          </p>
        )}
        {!isLoadingGallery && galleryProfiles.length > 0 && filteredProfiles.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t('admin.profileSources.noMatch')}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredProfiles.map((p: RemoteProfile) => {
            const imported = isImported(p)
            return (
              <div key={p.source_url} className="rounded-lg border bg-card p-4">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <div>
                    <div className="font-medium">{p.name}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <Badge variant="secondary" className="text-xs">
                        {p.extension_count} ext.
                      </Badge>
                      {imported && (
                        <button
                          type="button"
                          onClick={() => setConfirmRemove(p)}
                          className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-green-600 px-2 py-0.5 text-xs text-green-600 transition-colors hover:bg-green-50 dark:hover:bg-green-950"
                          title={t('admin.profileSources.removeImported')}
                        >
                          <CheckCircle2 className="h-3 w-3" />
                          {t('admin.profileSources.flagImported')}
                        </button>
                      )}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant={imported ? 'ghost' : 'default'}
                    onClick={() => importProfile.mutate(p.source_url)}
                    disabled={imported || importProfile.isPending}
                  >
                    {importProfile.isPending
                      ? t('admin.profileSources.importing')
                      : t('admin.profileSources.import')}
                  </Button>
                </div>
                <div className="mt-2 text-sm text-muted-foreground">
                  {p.description}
                </div>
                <div className="mt-2 truncate text-xs text-muted-foreground font-mono">
                  {p.source_base}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* ── Dialog confirmation retrait ──────────────────────────────── */}
      <Dialog open={Boolean(confirmRemove)} onOpenChange={(o) => !o && setConfirmRemove(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.profileSources.removeConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {t('admin.profileSources.removeConfirmDescription', { name: confirmRemove?.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmRemove(null)}>
              {t('profiles.delete.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleRemoveConfirm}
              disabled={deleteSharedMutation.isPending}
            >
              {t('admin.profileSources.removeImported')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
