import { useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { AppWindow, Plus, X } from 'lucide-react'
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
import {
  useApplications,
  useAddApplication,
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

function AppTile({ app, onDelete }: { app: KioskApplication; onDelete: (app: KioskApplication) => void }) {
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
      <button
        type="button"
        onClick={() => onDelete(app)}
        aria-label={t('applications.remove', { name: app.name })}
        className="absolute right-1.5 top-1.5 hidden rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive group-hover:block"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

const EMPTY_FORM = { name: '', url: '', icon: '' }

function AddApplicationDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [form, setForm] = useState(EMPTY_FORM)
  const [probing, setProbing] = useState(false)
  const add = useAddApplication()
  // La saisie manuelle de l'icône prime : plus d'auto-remplissage après édition.
  const iconEdited = useRef(false)
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
    add.mutate(
      { name: form.name.trim(), url, icon: form.icon.trim() },
      {
        onSuccess: () => onClose(),
        onError: (err) => toast.error(err.message),
      }
    )
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('applications.addTitle')}</DialogTitle>
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
            <Button type="submit" disabled={!form.name.trim() || !form.url.trim() || add.isPending}>
              {add.isPending ? '…' : t('applications.add')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default function ApplicationsPage() {
  const { t } = useTranslation()
  const { data: apps = [], isLoading } = useApplications()
  const [addOpen, setAddOpen] = useState(false)
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
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />
          {t('applications.addButton')}
        </Button>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">…</p>
      ) : apps.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          {t('applications.empty')}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {apps.map((app) => (
            <AppTile key={app.id} app={app} onDelete={handleDelete} />
          ))}
        </div>
      )}

      {addOpen && <AddApplicationDialog onClose={() => setAddOpen(false)} />}
    </div>
  )
}
