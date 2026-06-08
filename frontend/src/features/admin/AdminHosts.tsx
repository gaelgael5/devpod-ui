import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useHosts, useAddHost, type HostConfig } from './useHosts'

const EMPTY: HostConfig = { name: '', type: 'docker-tls', default: false, docker_host: '', address: '', key_path: '' }

export default function AdminHosts() {
  const { t } = useTranslation()
  const { data: hosts, isLoading, isError } = useHosts()
  const addHost = useAddHost()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<HostConfig>(EMPTY)

  function set<K extends keyof HostConfig>(k: K, v: HostConfig[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function handleClose(o: boolean) {
    if (!o) setForm(EMPTY)
    setOpen(o)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    addHost.mutate(form, { onSuccess: () => handleClose(false) })
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('admin.hosts')}</h1>
        <Button size="sm" onClick={() => setOpen(true)}>{t('admin.addHost')}</Button>
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
              </tr>
            </thead>
            <tbody>
              {hosts.map((h: HostConfig) => (
                <tr key={h.name} className="border-b last:border-0">
                  <td className="px-4 py-2 font-medium">{h.name}</td>
                  <td className="px-4 py-2 text-muted-foreground">{h.type}</td>
                  <td className="px-4 py-2 text-muted-foreground font-mono text-xs">{h.docker_host ?? '—'}</td>
                  <td className="px-4 py-2">
                    {h.default ? (
                      <span className="text-green-600">✓</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.addHost')}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="h-name">{t('admin.form.hostName')}</Label>
              <Input
                id="h-name"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="docker-node1"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t('admin.form.hostType')}</Label>
              <Select value={form.type} onValueChange={(v) => set('type', v as HostConfig['type'])}>
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
                <Input
                  id="h-docker"
                  value={form.docker_host ?? ''}
                  onChange={(e) => set('docker_host', e.target.value)}
                  placeholder="tcp://192.168.1.50:2376"
                />
              </div>
            )}
            {form.type === 'ssh' && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="h-address">{t('admin.form.address')}</Label>
                <Input
                  id="h-address"
                  value={form.address ?? ''}
                  onChange={(e) => set('address', e.target.value)}
                  placeholder="user@192.168.1.50"
                />
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="h-keypath">{t('admin.form.keyPath')}</Label>
              <Input
                id="h-keypath"
                value={form.key_path ?? ''}
                onChange={(e) => set('key_path', e.target.value)}
                placeholder="/data/certs/pve1"
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.default ?? false}
                onChange={(e) => set('default', e.target.checked)}
              />
              {t('admin.form.makeDefault')}
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => handleClose(false)}>
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={addHost.isPending}>
                {t('admin.form.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
