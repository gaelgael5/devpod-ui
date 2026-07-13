import { useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { AppWindow, Pencil, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useUserStore } from '@/store/user'
import {
  useApplications,
  useAddApplication,
  useUpdateApplication,
  useDeleteApplication,
  probeFavicon,
  type KioskApplication,
} from './useApplications'

function isImageUrl(icon: string): boolean {
  return icon.startsWith('https://') || icon.startsWith('http://')
}

/** Icône de tuile : URL http(s) → image, sinon emoji/texte court, vide → fallback. */
function AppIcon({ icon }: { icon: string }) {
  if (!icon) return <AppWindow className="h-10 w-10 text-muted-foreground" />
  if (isImageUrl(icon)) {
    return <img src={icon} alt="" className="h-10 w-10 rounded object-contain" loading="lazy" />
  }
  return <span className="text-4xl leading-none">{icon}</span>
}

function AppTile({
  app,
  isAdmin,
  onEdit,
  onDelete,
}: {
  app: KioskApplication
  isAdmin: boolean
  onEdit: (app: KioskApplication) => void
  onDelete: (app: KioskApplication) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="group relative rounded-lg border bg-card transition-colors hover:border-primary/50">
      <a
        href={app.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex flex-col items-center gap-3 p-6"
      >
        <AppIcon icon={app.icon} />
        <span className="max-w-full truncate text-sm font-medium text-foreground">{app.name}</span>
      </a>
      {isAdmin && (
        <div className="absolute right-1.5 top-1.5 hidden gap-1 group-hover:flex">
          <button
            type="button"
            onClick={() => onEdit(app)}
            aria-label={t('applications.edit', { name: app.name })}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onDelete(app)}
            aria-label={t('applications.remove', { name: app.name })}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}

/** Dialog d'ajout (app absent) ou d'édition (app fourni). */
function ApplicationDialog({ app, onClose }: { app: KioskApplication | null; onClose: () => void }) {
  const { t } = useTranslation()
  const [form, setForm] = useState(
    app ? { name: app.name, url: app.url, icon: app.icon } : { name: '', url: '', icon: '' }
  )
  const [probing, setProbing] = useState(false)
  const add = useAddApplication()
  const update = useUpdateApplication()
  const pending = add.isPending || update.isPending
  // La saisie manuelle de l'icône prime : plus d'auto-remplissage après édition.
  // En mode édition, une icône déjà présente est traitée comme une saisie.
  const iconEdited = useRef(Boolean(app?.icon))
  // Ignore le résultat d'un probe périmé (URL retapée entre-temps).
  const probeSeq = useRef(0)

  async function detectFavicon() {
    const url = form.url.trim()
    if (iconEdited.current || !/^https?:\/\//i.test(url)) return
    const seq = ++probeSeq.current
    setProbing(true)
    try {
      const favicon = await probeFavicon(url)
      if (seq !== probeSeq.current || iconEdited.current) return
      setForm((f) => ({ ...f, icon: favicon ?? '' }))
    } catch {
      // Probe best-effort : en échec on laisse simplement l'icône vide.
    } finally {
      if (seq === probeSeq.current) setProbing(false)
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const url = form.url.trim()
    if (!/^https?:\/\//i.test(url)) {
      toast.error(t('applications.urlHint'))
      return
    }
    const body = { name: form.name.trim(), url, icon: form.icon.trim() }
    const opts = {
      onSuccess: () => onClose(),
      onError: (err: Error) => toast.error(err.message),
    }
    if (app) update.mutate({ id: app.id, ...body }, opts)
    else add.mutate(body, opts)
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{app ? t('applications.editTitle') : t('applications.addTitle')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="app-name">{t('applications.nameLabel')}</Label>
            <Input
              id="app-name"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder={t('applications.namePlaceholder')}
              maxLength={60}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-url">{t('applications.urlLabel')}</Label>
            <Input
              id="app-url"
              type="url"
              value={form.url}
              onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
              onBlur={detectFavicon}
              placeholder={t('applications.urlPlaceholder')}
              maxLength={2000}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="app-icon">{t('applications.iconLabel')}</Label>
            <div className="flex items-center gap-3">
              <Input
                id="app-icon"
                value={form.icon}
                onChange={(e) => { iconEdited.current = true; setForm((f) => ({ ...f, icon: e.target.value })) }}
                placeholder={t('applications.iconPlaceholder')}
                maxLength={300}
                className="flex-1"
              />
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded border bg-muted/30">
                {probing ? (
                  <span className="text-xs text-muted-foreground animate-pulse">…</span>
                ) : (
                  <AppIcon icon={form.icon.trim()} />
                )}
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              {probing ? t('applications.iconDetecting') : t('applications.iconHint')}
            </p>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              {t('applications.cancel')}
            </Button>
            <Button type="submit" disabled={!form.name.trim() || !form.url.trim() || pending}>
              {pending ? '…' : app ? t('applications.save') : t('applications.add')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default function ApplicationsPage() {
  const { t } = useTranslation()
  const isAdmin = useUserStore((s) => s.isAdmin())
  const { data: apps = [], isLoading } = useApplications()
  // null = fermé ; 'new' = ajout ; KioskApplication = édition.
  const [dialog, setDialog] = useState<KioskApplication | 'new' | null>(null)
  const del = useDeleteApplication()

  function handleDelete(app: KioskApplication) {
    del.mutate(app.id, {
      onError: (err) => toast.error(err.message),
    })
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{t('applications.title')}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t('applications.intro')}</p>
        </div>
        {isAdmin && (
          <Button onClick={() => setDialog('new')}>
            <Plus className="mr-1 h-4 w-4" />
            {t('applications.addButton')}
          </Button>
        )}
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">…</p>
      ) : apps.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          {isAdmin ? t('applications.empty') : t('applications.emptyUser')}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {apps.map((app) => (
            <AppTile
              key={app.id}
              app={app}
              isAdmin={isAdmin}
              onEdit={(a) => setDialog(a)}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {dialog !== null && (
        <ApplicationDialog app={dialog === 'new' ? null : dialog} onClose={() => setDialog(null)} />
      )}
    </div>
  )
}
