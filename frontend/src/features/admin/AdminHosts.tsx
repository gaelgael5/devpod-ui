import { useState } from 'react'
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
import { useHosts, useAddHost, useUpdateHost, useDeleteHost, useHostCert, type HostConfig } from './useHosts'
import GenerateHostDialog from './GenerateHostDialog'
import SshTerminalWindow from './SshTerminalWindow'

const EMPTY: HostConfig = { name: '', type: 'docker-tls', default: false, docker_host: '', address: '', key_path: '' }

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
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [form, setForm] = useState<HostConfig>(EMPTY)
  const [sshTarget, setSshTarget] = useState<HostConfig | null>(null)

  function set<K extends keyof HostConfig>(k: K, v: HostConfig[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function handleClose(o: boolean) {
    if (!o) { setForm(EMPTY); setMode('add'); setShowCert(false) }
    setOpen(o)
  }

  function openAdd() {
    setForm(EMPTY); setMode('add'); setShowCert(false); setOpen(true)
  }

  function openEdit(host: HostConfig) {
    setForm({ ...host }); setMode('edit'); setShowCert(false); setOpen(true)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const mutation = mode === 'edit' ? updateHost : addHost
    mutation.mutate(form, { onSuccess: () => handleClose(false) })
  }

  function handleGenerated(config: HostConfig) {
    setForm(config); setMode('add'); setShowCert(false); setOpen(true)
  }

  function confirmDelete(name: string) { setDeleteTarget(name) }
  function cancelDelete() { setDeleteTarget(null) }
  function doDelete() {
    if (deleteTarget) deleteHost.mutate(deleteTarget, { onSuccess: () => setDeleteTarget(null) })
  }

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
                <tr key={h.name} className="border-b last:border-0">
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
                        onClick={() => confirmDelete(h.name)} aria-label={t('admin.deleteHost')}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                      {h.type === 'ssh' && (
                        <>
                          <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
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
                        </>
                      )}
                    </div>
                  </td>
                </tr>
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
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="h-keypath">{t('admin.form.keyPath')}</Label>
              <Input id="h-keypath" value={form.key_path ?? ''}
                onChange={(e) => set('key_path', e.target.value)}
                placeholder="/data/certs/pve1" />
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

      {sshTarget && (
        <SshTerminalWindow host={sshTarget} onClose={() => setSshTarget(null)} />
      )}
    </div>
  )
}
