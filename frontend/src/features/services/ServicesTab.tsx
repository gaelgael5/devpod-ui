import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ExternalLink, Globe, Pencil, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useProfiles } from '@/features/mcp/api'
import {
  useCreateService, useDeleteService, useServices, useUpdateService, type UserService,
} from './api'

// ── Dialog création / édition ─────────────────────────────────────────────────

function ServiceFormDialog({
  service,
  open,
  onClose,
}: {
  service?: UserService
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { data: profiles = [] } = useProfiles()
  const create = useCreateService()
  const update = useUpdateService()
  const [name, setName] = useState(service?.name ?? '')
  const [url, setUrl] = useState(service?.url ?? '')
  const [profileId, setProfileId] = useState(service?.mcp_profile_id ?? '')

  const isPending = create.isPending || update.isPending

  function close() {
    setName(service?.name ?? '')
    setUrl(service?.url ?? '')
    setProfileId(service?.mcp_profile_id ?? '')
    create.reset()
    update.reset()
    onClose()
  }

  function submit() {
    const body = { name: name.trim(), url: url.trim(), mcp_profile_id: profileId }
    const onError = (e: unknown) =>
      toast.error(e instanceof Error ? e.message : t('errors.generic'))
    if (service) {
      update.mutate({ id: service.id, ...body }, { onSuccess: close, onError })
    } else {
      create.mutate(body, { onSuccess: close, onError })
    }
  }

  const canSubmit = !!name.trim() && !!url.trim() && !!profileId

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {service ? t('services.editTitle') : t('services.createTitle')}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="svc-name">{t('services.name')}</Label>
            <Input
              id="svc-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('services.namePlaceholder')}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="svc-url">{t('services.url')}</Label>
            <Input
              id="svc-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://grafana.example.org"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="svc-profile">{t('services.mcpProfile')}</Label>
            <Select value={profileId} onValueChange={setProfileId}>
              <SelectTrigger id="svc-profile">
                <SelectValue placeholder={t('services.mcpProfilePlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {profiles.map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {profiles.length === 0 && (
              <p className="text-xs text-muted-foreground">{t('services.noProfileHint')}</p>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={isPending || !canSubmit}>
            {isPending ? t('common.loading') : t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Card service ───────────────────────────────────────────────────────────────

function ServiceCard({ service }: { service: UserService }) {
  const { t } = useTranslation()
  const del = useDeleteService()
  const [editOpen, setEditOpen] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)

  return (
    <div className="flex items-start gap-3 rounded-lg border bg-card p-4">
      <Globe className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{service.name}</span>
          {service.mcp_profile_name ? (
            <Badge variant="outline" className="text-xs">{service.mcp_profile_name}</Badge>
          ) : (
            <Badge variant="secondary" className="text-xs">{t('services.noProfile')}</Badge>
          )}
        </div>
        <a
          href={service.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground hover:text-primary hover:underline"
        >
          {service.url}
          <ExternalLink className="h-3 w-3 shrink-0" />
        </a>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button size="sm" variant="ghost" onClick={() => setEditOpen(true)}>
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        {confirmDel ? (
          <>
            <Button
              size="sm"
              variant="destructive"
              disabled={del.isPending}
              onClick={() =>
                del.mutate(service.id, {
                  onSuccess: () => setConfirmDel(false),
                  onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
                })
              }
            >
              {t('services.confirmDelete')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDel(false)}>
              {t('common.cancel')}
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => setConfirmDel(true)}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      <ServiceFormDialog service={service} open={editOpen} onClose={() => setEditOpen(false)} />
    </div>
  )
}

// ── Composant principal ───────────────────────────────────────────────────────

export default function ServicesTab() {
  const { t } = useTranslation()
  const { data: services = [], isLoading } = useServices()
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('services.sectionTitle')}</h2>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />{t('services.create')}
        </Button>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && services.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('services.empty')}</p>
      )}
      <div className="flex flex-col gap-2">
        {services.map((s) => (
          <ServiceCard key={s.id} service={s} />
        ))}
      </div>
      <ServiceFormDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  )
}
