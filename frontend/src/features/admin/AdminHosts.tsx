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
import { cn } from '@/lib/utils'
import { useHosts, useAddHost, useUpdateHost, useDeleteHost, useHostCert, useDestroyVm, useHostWorkspaces, useTestHostsSummary, type HostConfig, type HostCreatePayload, type HostUserWorkspaces, type UserTestGroup } from './useHosts'
import BootstrapSshDialog from './BootstrapSshDialog'
import GenerateHostDialog from './GenerateHostDialog'
import TestHostParamsDialog from './TestHostParamsDialog'
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

const DEPLOY_STATUS_DOT: Record<string, string> = {
  running: 'bg-green-500',
  stopped: 'bg-yellow-500',
  created: 'bg-blue-400',
  error:   'bg-destructive',
  partial: 'bg-orange-400',
}
const DEPLOY_STATUS_TEXT: Record<string, string> = {
  running: 'text-green-600',
  stopped: 'text-yellow-600',
  created: 'text-blue-500',
  error:   'text-destructive',
  partial: 'text-orange-500',
}

// ─── Primitives arborescence ──────────────────────────────────────────────────

function TreeNode({
  connector = '└',
  children,
}: {
  connector?: '└' | '├'
  children: React.ReactNode
}) {
  return (
    <div className="flex items-start gap-1">
      <span className="mt-0.5 shrink-0 font-mono text-[10px] text-muted-foreground/50 select-none">
        {connector}
      </span>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )
}

function TreeGroup({ children }: { children: React.ReactNode }) {
  return <div className="mt-0.5 pl-3 border-l border-border/30">{children}</div>
}

// ─── Panel workspaces ─────────────────────────────────────────────────────────

function HostWorkspacesPanel({ name }: { name: string }) {
  const { t } = useTranslation()
  const { data, isLoading } = useHostWorkspaces(name)

  if (isLoading) return <span className="text-xs text-muted-foreground">…</span>
  if (!data || data.length === 0) return <span className="text-xs text-muted-foreground">—</span>

  return (
    <div className="py-0.5 space-y-0.5">
      {(data as HostUserWorkspaces[]).map((u, ui, ua) => {
        const sorted = [...u.workspaces].sort((a, b) => a.name.localeCompare(b.name))
        return (
          <TreeNode key={u.login} connector={ui === ua.length - 1 ? '└' : '├'}>
            <span className="text-xs font-medium">{u.login}</span>
            <TreeGroup>
              {sorted.map((ws, wi) => {
                const s = ws.status
                return (
                  <TreeNode key={ws.name} connector={wi === sorted.length - 1 ? '└' : '├'}>
                    <span className={cn('inline-flex items-center gap-1 text-xs', STATUS_TEXT[s] ?? STATUS_TEXT.unknown)}>
                      <span className={cn('h-1.5 w-1.5 rounded-full shrink-0', STATUS_DOT[s] ?? STATUS_DOT.unknown)} />
                      {ws.name}
                      <span className="opacity-50">({t(`workspaces.status.${s}`, s)})</span>
                    </span>
                  </TreeNode>
                )
              })}
            </TreeGroup>
          </TreeNode>
        )
      })}
    </div>
  )
}

// ─── Section test hosts groupés par workspace ─────────────────────────────────

type HostActions = {
  onEdit: (h: HostConfig) => void
  onDelete: (h: HostConfig) => void
  onSsh: (h: HostConfig) => void
  onBootstrap: (h: HostConfig) => void
}

function TestHostsGroupedSection({
  hosts,
  actions,
}: {
  hosts: HostConfig[]
  actions: HostActions
}) {
  const { t } = useTranslation()
  const userGroups = useTestHostsSummary(hosts)

  if (userGroups.length === 0) return null

  return (
    <div className="mt-4 flex flex-col gap-4">
      <h2 className="text-sm font-semibold text-muted-foreground px-1">{t('admin.testHost.sectionTitle')}</h2>

      {userGroups.map((userGroup: UserTestGroup) => (
        <div key={userGroup.owner_login} className="rounded-lg border">
          {/* En-tête utilisateur */}
          <div className="flex items-center gap-2 border-b bg-muted/60 px-4 py-2">
            <span className="text-sm font-semibold">{userGroup.owner_login}</span>
          </div>

          {/* Workspaces de cet utilisateur */}
          <div className="divide-y">
            {userGroup.workspaces.map((wsGroup, wsi) => (
              <div key={wsGroup.workspace_name}>
                {/* En-tête workspace */}
                <div className="flex items-center gap-2 px-4 py-2 bg-muted/20">
                  <span className="font-mono text-[10px] text-muted-foreground/50 select-none">└</span>
                  <span className="text-xs font-semibold">{wsGroup.workspace_name}</span>
                </div>

                {/* Machines de ce workspace */}
                <div className="divide-y divide-border/40">
                  {wsGroup.entries.map(({ host, info, deployments, loading }, mi) => (
                    <div key={host.name} className="pl-8 pr-4 py-2.5">
                      {/* Ligne machine : alias · nom · adresse · actions */}
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[10px] text-muted-foreground/50 select-none shrink-0">
                          {mi === wsGroup.entries.length - 1 ? '└' : '├'}
                        </span>
                        {info?.alias && (
                          <span className="font-mono text-xs font-semibold bg-muted rounded px-1.5 py-0.5 shrink-0">
                            {info.alias}
                          </span>
                        )}
                        <span className="text-xs font-medium shrink-0">{host.name}</span>
                        <span className="text-xs text-muted-foreground font-mono flex-1 truncate">
                          {host.address || '—'}
                        </span>
                        <div className="flex items-center gap-1 shrink-0">
                          <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => actions.onEdit(host)}>
                            <Pencil className="h-3 w-3" />
                          </Button>
                          <Button size="icon" variant="ghost" className="h-6 w-6 text-destructive hover:text-destructive" onClick={() => actions.onDelete(host)}>
                            <Trash2 className="h-3 w-3" />
                          </Button>
                          {!host.host_cert_slug && (
                            <Button size="sm" variant="outline"
                              className="h-6 px-2 text-xs font-semibold text-amber-700 border-amber-600 hover:bg-amber-50"
                              onClick={() => actions.onBootstrap(host)}>
                              {t('admin.bootstrap.btn')}
                            </Button>
                          )}
                          {host.host_cert_slug && (
                            <Button size="sm" variant="outline"
                              className="h-6 px-2 text-xs font-semibold text-green-700 border-green-600 hover:bg-green-50"
                              onClick={() => actions.onSsh(host)}>
                              {t('admin.sshTerminal.openBtn')}
                            </Button>
                          )}
                        </div>
                      </div>

                      {/* Services compose */}
                      <div className="mt-1.5 pl-5 border-l border-border/30 ml-1">
                        {loading && <span className="text-xs text-muted-foreground">…</span>}
                        {!loading && deployments.length === 0 && (
                          <span className="text-xs text-muted-foreground">{t('admin.testHost.noServices')}</span>
                        )}
                        {deployments.map((dep, di) => {
                          const s = dep.status
                          return (
                            <TreeNode key={dep.id} connector={di === deployments.length - 1 ? '└' : '├'}>
                              <span
                                title={dep.last_error ?? undefined}
                                className={cn('inline-flex items-center gap-1.5 text-xs', DEPLOY_STATUS_TEXT[s] ?? DEPLOY_STATUS_TEXT.error)}
                              >
                                <span className={cn('h-1.5 w-1.5 rounded-full shrink-0', DEPLOY_STATUS_DOT[s] ?? DEPLOY_STATUS_DOT.error)} />
                                <span className="font-medium">{dep.template_name}</span>
                                <span className="opacity-60">{dep.template_version}</span>
                                {dep.host_ports.length > 0 && (
                                  <span className="font-mono opacity-60">:{dep.host_ports.join(',')}</span>
                                )}
                              </span>
                            </TreeNode>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
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
  const addHost = useAddHost()
  const updateHost = useUpdateHost()
  const deleteHost = useDeleteHost()

  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<DialogMode>('add')
  const [showCert, setShowCert] = useState(false)
  const [generateOpen, setGenerateOpen] = useState(false)
  const [testParamsOpen, setTestParamsOpen] = useState(false)
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
          <Button size="sm" variant="outline" onClick={() => setTestParamsOpen(true)}>
            {t('admin.testHostParams.btn')}
          </Button>
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
      {hosts && hosts.length > 0 && (() => {
        const wsHosts = hosts.filter((h: HostConfig) => h.usage !== 'tests')
        const testHosts = hosts.filter((h: HostConfig) => h.usage === 'tests')
        const hostActions: HostActions = {
          onEdit: openEdit,
          onDelete: confirmDelete,
          onSsh: setSshTarget,
          onBootstrap: setBootstrapTarget,
        }
        return (
          <>
            {wsHosts.length > 0 && (
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
                    {wsHosts.map((h: HostConfig) => (
                      <Fragment key={h.name}>
                        <tr className="border-b">
                          <td className="px-4 py-2 font-medium">{h.name}</td>
                          <td className="px-4 py-2 text-muted-foreground">{h.type}</td>
                          <td className="px-4 py-2 text-muted-foreground font-mono text-xs">
                            {h.type === 'ssh' ? (h.address || '—') : (h.docker_host || '—')}
                          </td>
                          <td className="px-4 py-2">
                            {h.default
                              ? <span className="text-green-600">✓</span>
                              : <span className="text-muted-foreground">—</span>}
                          </td>
                          <td className="px-4 py-2">
                            <div className="flex items-center justify-end gap-1">
                              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEdit(h)}>
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                              <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive hover:text-destructive" onClick={() => confirmDelete(h)}>
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                              {h.type === 'ssh' && (
                                <>
                                  <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
                                  {!h.host_cert_slug && (
                                    <Button size="sm" variant="outline"
                                      className="h-7 px-2 text-xs font-semibold text-amber-700 border-amber-600 hover:bg-amber-50"
                                      onClick={() => setBootstrapTarget(h)}>
                                      {t('admin.bootstrap.btn')}
                                    </Button>
                                  )}
                                  {h.host_cert_slug && (
                                    <Button size="sm" variant="outline"
                                      className="h-7 px-2 text-xs font-semibold text-green-700 border-green-600 hover:bg-green-50"
                                      onClick={() => setSshTarget(h)}>
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
            <TestHostsGroupedSection hosts={testHosts} actions={hostActions} />
          </>
        )
      })()}

      <GenerateHostDialog
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        onGenerated={handleGenerated}
      />

      <TestHostParamsDialog
        open={testParamsOpen}
        onClose={() => setTestParamsOpen(false)}
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
