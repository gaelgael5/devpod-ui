import { Fragment, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, KeyRound, Pencil, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { cn } from '@/lib/utils'
import { useHosts, useAddHost, useUpdateHost, useDeleteHost, useHostCert, useDestroyVm, useHostWorkspaces, type HostConfig, type HostCreatePayload, type HostUserWorkspaces } from './useHosts'
import { useVaultKeys, type VaultKey } from '@/features/vault/api'
import BootstrapSshDialog from './BootstrapSshDialog'
import GenerateHostDialog from './GenerateHostDialog'
import SshTerminalWindow from './SshTerminalWindow'

const EMPTY: HostCreatePayload = {
  name: '',
  type: 'docker-tls',
  default: false,
  docker_host: '',
  address: '',
  proxmox_node: '',
  vmid: '',
  ci_password: '',
  storage_type: 'local',
  vault_identifier: '',
}

type DialogMode = 'add' | 'edit'

// ─── Cert viewer ─────────────────────────────────────────────────────────────

function CertViewer({ name }: { name: string }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, error } = useHostCert(name, true)

  if (isLoading) return <p className="text-xs text-muted-foreground">…</p>
  if (isError) {
    const msg = error instanceof Error ? error.message : t('errors.generic')
    return <p className="text-xs text-destructive">{msg}</p>
  }
  if (!data) return null

  function copy(content: string) {
    navigator.clipboard.writeText(content).catch(() => {})
  }

  return (
    <div className="flex flex-col gap-3">
      {(Object.entries(data) as [string, string][]).map(([filename, content]) => (
        <div key={filename} className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-medium">{filename}</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => copy(content)}
            >
              <Copy className="h-3 w-3 mr-1" />
              {t('admin.form.copyCert')}
            </Button>
          </div>
          <textarea
            readOnly
            value={content}
            className="h-28 w-full resize-none rounded-md border bg-muted px-3 py-2 font-mono text-xs"
          />
        </div>
      ))}
    </div>
  )
}

// ─── Logs streaming destroy ───────────────────────────────────────────────────

function DestroyLog({ logs, running, error }: { logs: string; running: boolean; error: string | null }) {
  const { t } = useTranslation()
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  return (
    <pre
      ref={logRef}
      className="h-56 overflow-y-auto rounded-md bg-muted p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap"
    >
      {logs || (running ? t('admin.destroyVm.running') : '')}
      {error && <span className="text-destructive">{'\n'}{error}</span>}
    </pre>
  )
}

// ─── Workspaces par utilisateur ──────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  running:      'bg-green-500',
  stopped:      'bg-yellow-500',
  provisioning: 'bg-primary',
  failed:       'bg-destructive',
  unknown:      'bg-muted-foreground',
}

const STATUS_TEXT: Record<string, string> = {
  running:      'text-green-600',
  stopped:      'text-yellow-600',
  provisioning: 'text-primary',
  failed:       'text-destructive',
  unknown:      'text-muted-foreground',
}

function HostWorkspacesPanel({ name }: { name: string }) {
  const { t } = useTranslation()
  const { data, isLoading } = useHostWorkspaces(name)

  if (isLoading) return <span className="text-xs text-muted-foreground">…</span>
  if (!data || data.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>
  }

  return (
    <div className="flex flex-wrap gap-x-6 gap-y-1">
      {(data as HostUserWorkspaces[]).map((u) => (
        <div key={u.login} className="flex items-start gap-2">
          <span className="text-xs font-medium text-foreground whitespace-nowrap">{u.login}</span>
          <div className="flex flex-wrap gap-1">
            {u.workspaces.map((ws) => {
              const s = ws.status
              return (
                <span
                  key={ws.name}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs',
                    STATUS_TEXT[s] ?? STATUS_TEXT.unknown,
                  )}
                >
                  <span className={cn('h-1.5 w-1.5 rounded-full shrink-0', STATUS_DOT[s] ?? STATUS_DOT.unknown)} />
                  {ws.name}
                  <span className="opacity-60">({t(`workspaces.status.${s}`, s)})</span>
                </span>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Composant principal ──────────────────────────────────────────────────────

export default function AdminHosts() {
  const { t } = useTranslation()
  const { data: hosts, isLoading, isError } = useHosts()
  const { data: vaultKeys = [] as VaultKey[] } = useVaultKeys()
  const addHost = useAddHost()
  const updateHost = useUpdateHost()
  const deleteHost = useDeleteHost()

  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<DialogMode>('add')
  const [showCert, setShowCert] = useState(false)
  const [generateOpen, setGenerateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [destroyTarget, setDestroyTarget] = useState<HostConfig | null>(null)
  const [form, setForm] = useState<HostCreatePayload>(EMPTY)
  const [sshTarget, setSshTarget] = useState<HostConfig | null>(null)
  const [bootstrapTarget, setBootstrapTarget] = useState<HostConfig | null>(null)
  const destroyVm = useDestroyVm()
  const destroyStartedRef = useRef(false)

  function set<K extends keyof HostCreatePayload>(k: K, v: HostCreatePayload[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function handleClose(o: boolean) {
    if (!o) { setForm(EMPTY); setMode('add'); setShowCert(false) }
    setOpen(o)
  }

  function openAdd() {
    const isFirst = !hosts || hosts.length === 0
    setForm({ ...EMPTY, default: isFirst }); setMode('add'); setShowCert(false); setOpen(true)
  }

  function openEdit(host: HostConfig) {
    setForm({
      name: host.name,
      type: host.type,
      default: host.default ?? false,
      docker_host: host.docker_host ?? '',
      address: host.address ?? '',
      proxmox_node: host.proxmox_node ?? '',
      vmid: host.vmid ?? '',
      ci_password: '',  // toujours vide en édition (secret non visible)
      storage_type: host.storage_type ?? 'local',
      vault_identifier: host.vault_identifier ?? '',
    })
    setMode('edit'); setShowCert(false); setOpen(true)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const payload: HostCreatePayload = {
      name: form.name,
      type: form.type,
      default: form.default,
      docker_host: form.docker_host,
      address: form.address,
      proxmox_node: form.proxmox_node,
      vmid: form.vmid,
      ci_password: form.ci_password ?? '',
      storage_type: form.storage_type,
      vault_identifier: form.vault_identifier,
    }
    const mutation = mode === 'edit' ? updateHost : addHost
    mutation.mutate(payload, { onSuccess: () => handleClose(false) })
  }

  function handleGenerated(config: HostConfig, ciPassword?: string) {
    const isFirst = !hosts || hosts.length === 0
    setForm({
      name: config.name,
      type: config.type,
      default: config.default ?? isFirst,
      docker_host: config.docker_host ?? '',
      address: config.address ?? '',
      proxmox_node: config.proxmox_node ?? '',
      vmid: config.vmid ?? '',
      ci_password: ciPassword ?? '',
      storage_type: config.storage_type ?? 'local',
      vault_identifier: config.vault_identifier ?? '',
    })
    setMode('add'); setShowCert(false); setOpen(true)
  }

  function confirmDelete(h: HostConfig) {
    if (h.vmid && h.proxmox_node) {
      destroyVm.reset()
      destroyStartedRef.current = false
      setDestroyTarget(h)
    } else {
      setDeleteTarget(h.name)
    }
  }
  function cancelDelete() { setDeleteTarget(null) }
  function doDelete() {
    if (deleteTarget) deleteHost.mutate(deleteTarget, { onSuccess: () => setDeleteTarget(null) })
  }

  function cancelDestroy() {
    setDestroyTarget(null)
    destroyVm.reset()
    destroyStartedRef.current = false
  }
  function doDestroyAndDelete() {
    if (!destroyTarget) return
    deleteHost.mutate(destroyTarget.name, {
      onSuccess: () => {
        setDestroyTarget(null)
        destroyVm.reset()
        destroyStartedRef.current = false
      },
    })
  }

  useEffect(() => {
    if (destroyTarget && destroyTarget.proxmox_node && destroyTarget.vmid && !destroyStartedRef.current) {
      destroyStartedRef.current = true
      void destroyVm.execute(destroyTarget.proxmox_node, destroyTarget.vmid)
    }
  }, [destroyTarget, destroyVm.execute])

  const isPending = addHost.isPending || updateHost.isPending

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('admin.hosts')}</h1>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setGenerateOpen(true)}>
            {t('admin.generate.btn')}
          </Button>
          <Button size="sm" onClick={openAdd}>{t('admin.addHost')}</Button>
        </div>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !hosts?.length && (
        <p className="text-muted-foreground">{t('admin.hostsEmpty')}</p>
      )}
      {hosts && hosts.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.name')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.type')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.host')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.default')}</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {hosts.map((h: HostConfig) => (
                <Fragment key={h.name}>
                  <tr className="border-b">
                    <td className="px-4 py-2 font-medium">{h.name}</td>
                    <td className="px-4 py-2 text-muted-foreground">{h.type}</td>
                    <td className="px-4 py-2 text-muted-foreground font-mono text-xs">{h.docker_host || '—'}</td>
                    <td className="px-4 py-2">
                      {h.default
                        ? <span className="text-green-600">✓</span>
                        : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEdit(h)}
                          aria-label={t('workspaces.actions.edit')}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => confirmDelete(h)} aria-label={t('admin.deleteHost')}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                        {h.type === 'ssh' && (
                          <>
                            <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
                            {!h.host_cert_slug && (
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 px-2 text-xs font-semibold text-amber-700 border-amber-600 hover:bg-amber-50"
                                onClick={() => setBootstrapTarget(h)}
                                aria-label={t('admin.bootstrap.btn')}
                              >
                                {t('admin.bootstrap.btn')}
                              </Button>
                            )}
                            {h.host_cert_slug && (
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 px-2 text-xs font-semibold text-green-700 border-green-600 hover:bg-green-50"
                                data-ssh=""
                                onClick={() => setSshTarget(h)}
                                aria-label={t('admin.sshTerminal.openBtn')}
                              >
                                {t('admin.sshTerminal.openBtn')}
                              </Button>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                  <tr className="border-b last:border-0 bg-muted/20">
                    <td colSpan={5} className="px-4 py-2">
                      <HostWorkspacesPanel name={h.name} />
                    </td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <GenerateHostDialog
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        onGenerated={handleGenerated}
      />

      {/* ── Dialogue ajout / édition ── */}
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {mode === 'edit' ? t('admin.editHost') : t('admin.addHost')}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="h-name">{t('admin.form.hostName')}</Label>
              <Input id="h-name" value={form.name} onChange={(e) => set('name', e.target.value)}
                placeholder="docker-node1" required
                readOnly={mode === 'edit'}
                className={mode === 'edit' ? 'bg-muted text-muted-foreground' : ''} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t('admin.form.hostType')}</Label>
              <Select value={form.type} onValueChange={(v) => { set('type', v as HostConfig['type']); setShowCert(false) }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="docker-tls">docker-tls</SelectItem>
                  <SelectItem value="ssh">ssh</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.type === 'docker-tls' && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="h-docker">{t('admin.form.dockerHost')}</Label>
                <Input id="h-docker" value={form.docker_host ?? ''}
                  onChange={(e) => set('docker_host', e.target.value)}
                  placeholder="tcp://192.168.1.50:2376" />
              </div>
            )}
            {form.type === 'ssh' && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="h-address">{t('admin.form.address')}</Label>
                <Input id="h-address" value={form.address ?? ''}
                  onChange={(e) => set('address', e.target.value)}
                  placeholder="user@192.168.1.50" />
              </div>
            )}
            <div className="space-y-2">
              <Label>{t('hosts.form.storage', 'Stockage des secrets')}</Label>
              <RadioGroup
                value={form.storage_type}
                onValueChange={(v) => setForm(f => ({
                  ...f,
                  storage_type: v as 'local' | 'harpocrate',
                  vault_identifier: v === 'local' ? '' : f.vault_identifier,
                }))}
                className="flex gap-4"
              >
                <div className="flex items-center gap-2">
                  <RadioGroupItem value="local" id="storage-local" />
                  <Label htmlFor="storage-local">{t('hosts.form.storage_local', 'Local (chiffré sur le serveur)')}</Label>
                </div>
                <div className="flex items-center gap-2">
                  <RadioGroupItem value="harpocrate" id="storage-harpo" disabled={vaultKeys.length === 0} />
                  <Label htmlFor="storage-harpo" className={vaultKeys.length === 0 ? 'text-muted-foreground' : ''}>
                    {t('hosts.form.storage_harpo', 'Harpocrate')}
                    {vaultKeys.length === 0 && <span className="ml-1 text-xs">({t('hosts.form.no_wallet', 'aucun wallet configuré')})</span>}
                  </Label>
                </div>
              </RadioGroup>

              {form.storage_type === 'harpocrate' && (
                <div className="space-y-1">
                  <Label>{t('hosts.form.vault_identifier', 'Wallet Harpocrate')}</Label>
                  <Select
                    value={form.vault_identifier}
                    onValueChange={(v) => setForm(f => ({ ...f, vault_identifier: v }))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t('hosts.form.vault_placeholder', 'Sélectionner un wallet…')} />
                    </SelectTrigger>
                    <SelectContent>
                      {vaultKeys.map((k: VaultKey) => (
                        <SelectItem key={k.identifier} value={k.identifier}>
                          {k.identifier}{k.description ? ` — ${k.description}` : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>

            <div className="space-y-1">
              <Label htmlFor="h-ci-password">{t('hosts.form.ci_password', 'Mot de passe console Proxmox (optionnel)')}</Label>
              <Input
                id="h-ci-password"
                type="password"
                value={form.ci_password ?? ''}
                onChange={(e) => setForm(f => ({ ...f, ci_password: e.target.value }))}
                placeholder={mode === 'edit' ? t('hosts.form.ci_password_keep', '(conserver le mot de passe existant)') : ''}
                autoComplete="new-password"
              />
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.default ?? false}
                onChange={(e) => set('default', e.target.checked)} />
              {t('admin.form.makeDefault')}
            </label>

            {/* ── Affichage certificats (docker-tls + édition seulement) ── */}
            {mode === 'edit' && form.type === 'docker-tls' && (
              <div className="flex flex-col gap-2 border-t pt-3">
                <Button type="button" variant="outline" size="sm"
                  className="self-start"
                  onClick={() => setShowCert((v) => !v)}>
                  <KeyRound className="h-3.5 w-3.5 mr-1.5" />
                  {showCert ? t('admin.form.hideCert') : t('admin.form.showCert')}
                </Button>
                {showCert && <CertViewer name={form.name} />}
              </div>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => handleClose(false)}>
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={isPending}>
                {t('admin.form.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Dialogue confirmation suppression ── */}
      <Dialog open={deleteTarget !== null} onOpenChange={(o) => { if (!o) cancelDelete() }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.deleteHostTitle')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {t('admin.deleteHostDescription', { name: deleteTarget ?? '' })}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={cancelDelete}>{t('workspaces.confirm.cancel')}</Button>
            <Button variant="destructive" onClick={doDelete} disabled={deleteHost.isPending}>
              {t('workspaces.confirm.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Dialogue destroy VM (host avec vmid) ── */}
      <Dialog open={destroyTarget !== null} onOpenChange={(o) => { if (!o) cancelDestroy() }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('admin.destroyVm.title', { name: destroyTarget?.name ?? '' })}</DialogTitle>
          </DialogHeader>
          <p className="text-xs text-muted-foreground -mt-1">
            {t('admin.destroyVm.vmidOnNode', {
              vmid: destroyTarget?.vmid ?? '',
              node: destroyTarget?.proxmox_node ?? '',
            })}
          </p>
          <DestroyLog logs={destroyVm.logs} running={destroyVm.running} error={destroyVm.error} />
          <DialogFooter>
            <Button variant="outline" onClick={cancelDestroy} disabled={deleteHost.isPending}>
              {t('admin.destroyVm.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={doDestroyAndDelete}
              disabled={destroyVm.running || deleteHost.isPending}
            >
              {t('admin.destroyVm.deleteHost')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {bootstrapTarget && (
        <BootstrapSshDialog
          host={bootstrapTarget}
          open={bootstrapTarget !== null}
          onClose={() => setBootstrapTarget(null)}
        />
      )}

      {sshTarget && (
        <SshTerminalWindow host={sshTarget} onClose={() => setSshTarget(null)} />
      )}
    </div>
  )
}
