import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BookOpen, Plus, Pencil, Trash2, ChevronRight, Check } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
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
import { Textarea } from '@/components/ui/textarea'
import {
  useProfiles,
  useProfileDetail,
  useCreateProfile,
  useUpdateProfile,
  useDeleteProfile,
  useUpsertEntry,
  useDeleteEntry,
  useBackends,
  useBackendKeys,
  useBackendCatalog,
  type MCPProfile,
} from './api'

// ── Dialog création / édition de profil ───────────────────────────────────────

function ProfileFormDialog({
  profile,
  open,
  onClose,
}: {
  profile?: MCPProfile
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const create = useCreateProfile()
  const update = useUpdateProfile()
  const [name, setName] = useState(profile?.name ?? '')
  const [description, setDescription] = useState(profile?.description ?? '')

  const isPending = create.isPending || update.isPending

  function close() {
    setName(profile?.name ?? '')
    setDescription(profile?.description ?? '')
    create.reset()
    update.reset()
    onClose()
  }

  function submit() {
    if (profile) {
      update.mutate(
        { id: profile.id, name, description },
        {
          onSuccess: close,
          onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
        },
      )
    } else {
      create.mutate(
        { name, description },
        {
          onSuccess: close,
          onError: (e) => toast.error(e instanceof Error ? e.message : t('errors.generic')),
        },
      )
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {profile ? t('mcp.profiles.editTitle') : t('mcp.profiles.createTitle')}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.profiles.name')}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.profiles.description')}</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={isPending || !name.trim()}>
            {isPending ? t('mcp.saving') : t('mcp.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Éditeur de services d'un profil ───────────────────────────────────────────

function EntryRow({
  profileId,
  backendId,
  backendName,
  namespace,
  currentTools,
  currentKeyId,
  onRemove,
}: {
  profileId: string
  backendId: string
  backendName: string
  namespace: string
  currentTools: string[] | null
  currentKeyId: string | null
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const upsert = useUpsertEntry(profileId)
  const { data: keys = [] } = useBackendKeys(backendId)
  const [expanded, setExpanded] = useState(false)

  const toolCount = currentTools === null ? t('mcp.profiles.allTools') : `${currentTools.length} tool(s)`

  return (
    <div className="rounded border p-2 flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="flex items-center gap-1 flex-1 text-left"
          onClick={() => setExpanded((v) => !v)}
        >
          <ChevronRight
            className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${expanded ? 'rotate-90' : ''}`}
          />
          <span className="text-sm font-medium">{backendName}</span>
          <Badge variant="outline" className="font-mono text-xs">{namespace}</Badge>
          <Badge variant="secondary" className="text-xs ml-auto">{toolCount}</Badge>
        </button>
        <Button
          size="sm"
          variant="ghost"
          className="text-destructive hover:text-destructive h-6 px-1.5"
          onClick={onRemove}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>

      {expanded && (
        <div className="mt-1 flex flex-col gap-2 pl-5">
          {keys.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground shrink-0">{t('mcp.profiles.serviceKey')}</span>
              <select
                className="flex-1 h-7 rounded border bg-background px-2 text-xs"
                value={currentKeyId ?? ''}
                onChange={(e) =>
                  upsert.mutate({
                    backend_id: backendId,
                    backend_key_id: e.target.value || null,
                    tools: currentTools,
                  })
                }
              >
                <option value="">{t('mcp.profiles.autoKey')}</option>
                {keys.map((k) => (
                  <option key={k.id} value={k.id}>{k.slug}</option>
                ))}
              </select>
            </div>
          )}
          <ToolsEditor
            profileId={profileId}
            backendId={backendId}
            tools={currentTools}
            keyId={currentKeyId}
          />
        </div>
      )}
    </div>
  )
}

function ToolsEditor({
  profileId,
  backendId,
  tools,
  keyId,
}: {
  profileId: string
  backendId: string
  tools: string[] | null
  keyId: string | null
}) {
  const { t } = useTranslation()
  const upsert = useUpsertEntry(profileId)
  const { data: catalog = [] } = useBackendCatalog(backendId)

  const allSelected = tools === null

  function toggleAll() {
    upsert.mutate({
      backend_id: backendId,
      backend_key_id: keyId,
      tools: allSelected ? [] : null,
    })
  }

  function toggleTool(name: string) {
    const current = tools ?? catalog.map((t) => t.name)
    const next = current.includes(name) ? current.filter((t) => t !== name) : [...current, name]
    upsert.mutate({ backend_id: backendId, backend_key_id: keyId, tools: next })
  }

  if (catalog.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">{t('mcp.profiles.noToolsCatalog')}</p>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase text-muted-foreground">
          {t('mcp.profiles.tools')}
        </span>
        <button
          type="button"
          className="ml-auto text-xs text-primary underline-offset-2 hover:underline"
          onClick={toggleAll}
        >
          {allSelected ? t('mcp.profiles.restrictTools') : t('mcp.profiles.allowAllTools')}
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {catalog.map((tool) => {
          const active = allSelected || (tools ?? []).includes(tool.name)
          return (
            <button
              key={tool.name}
              type="button"
              onClick={() => toggleTool(tool.name)}
              title={tool.description || tool.name}
              className={`flex items-center gap-1 rounded border px-2 py-0.5 text-xs transition-colors ${
                active
                  ? 'border-primary/30 bg-primary/10 text-primary'
                  : 'border-border bg-muted/40 text-muted-foreground'
              }`}
            >
              {active && <Check className="h-2.5 w-2.5" />}
              <code>{tool.name}</code>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Dialog d'édition des services d'un profil ─────────────────────────────────

function ProfileEntriesDialog({
  profile,
  open,
  onClose,
}: {
  profile: MCPProfile
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { data: detail } = useProfileDetail(open ? profile.id : null)
  const { data: backends = [] } = useBackends()
  const upsert = useUpsertEntry(profile.id)
  const delEntry = useDeleteEntry(profile.id)

  const addedIds = new Set((detail?.entries ?? []).map((e) => e.backend_id))
  const available = backends.filter((b) => b.enabled && !addedIds.has(b.id))

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t('mcp.profiles.servicesTitle', { name: profile.name })}</DialogTitle>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto flex flex-col gap-3 pr-1">
          {/* Services déjà ajoutés */}
          {(detail?.entries ?? []).map((entry) => {
            const b = backends.find((x) => x.id === entry.backend_id)
            if (!b) return null
            return (
              <EntryRow
                key={entry.backend_id}
                profileId={profile.id}
                backendId={entry.backend_id}
                backendName={b.name}
                namespace={b.namespace}
                currentTools={entry.tools}
                currentKeyId={entry.backend_key_id}
                onRemove={() =>
                  delEntry.mutate(entry.backend_id, {
                    onError: (e) =>
                      toast.error(e instanceof Error ? e.message : t('errors.generic')),
                  })
                }
              />
            )
          })}

          {/* Ajouter un service */}
          {available.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold uppercase text-muted-foreground">
                {t('mcp.profiles.addService')}
              </span>
              <div className="flex flex-wrap gap-2">
                {available.map((b) => (
                  <Button
                    key={b.id}
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      upsert.mutate(
                        { backend_id: b.id, backend_key_id: null, tools: null },
                        {
                          onError: (e) =>
                            toast.error(e instanceof Error ? e.message : t('errors.generic')),
                        },
                      )
                    }
                  >
                    <Plus className="mr-1 h-3.5 w-3.5" />
                    {b.name}
                    <Badge variant="outline" className="ml-1 font-mono text-xs">{b.namespace}</Badge>
                  </Button>
                ))}
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button onClick={onClose}>{t('common.close')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Card profil ───────────────────────────────────────────────────────────────

function ProfileCard({ profile }: { profile: MCPProfile }) {
  const { t } = useTranslation()
  const del = useDeleteProfile()
  const [editOpen, setEditOpen] = useState(false)
  const [servicesOpen, setServicesOpen] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-start gap-3">
        <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium">{profile.name}</span>
          </div>
          {profile.description && (
            <p className="mt-0.5 text-xs text-muted-foreground">{profile.description}</p>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setServicesOpen(true)}
          >
            {t('mcp.profiles.configure')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setEditOpen(true)}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          {confirmDel ? (
            <>
              <Button
                size="sm"
                variant="destructive"
                disabled={del.isPending}
                onClick={() =>
                  del.mutate(profile.id, {
                    onSuccess: () => setConfirmDel(false),
                    onError: (e) =>
                      toast.error(e instanceof Error ? e.message : t('errors.generic')),
                  })
                }
              >
                {t('mcp.profiles.confirmDelete')}
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
      </div>

      <ProfileFormDialog
        profile={profile}
        open={editOpen}
        onClose={() => setEditOpen(false)}
      />
      <ProfileEntriesDialog
        profile={profile}
        open={servicesOpen}
        onClose={() => setServicesOpen(false)}
      />
    </div>
  )
}

// ── Composant principal ───────────────────────────────────────────────────────

export default function MCPProfiles() {
  const { t } = useTranslation()
  const { data: profiles = [], isLoading } = useProfiles()
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('mcp.profiles.sectionTitle')}</h2>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />{t('mcp.profiles.create')}
        </Button>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && profiles.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('mcp.profiles.empty')}</p>
      )}
      {profiles.map((p) => (
        <ProfileCard key={p.id} profile={p} />
      ))}
      <ProfileFormDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  )
}
