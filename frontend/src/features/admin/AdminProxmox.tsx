import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useAdminProxmox, type ProxmoxNodeConfig } from './useAdminProxmox'

const EMPTY = { name: '', address: '', ssh_user: 'root', ssh_port: 22, pve_node: 'pve' }

export default function AdminProxmox() {
  const { t } = useTranslation()
  const { nodesQuery, deleteNode, addNode } = useAdminProxmox()
  const { data: nodes, isLoading, isError } = nodesQuery
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const fileRef = useRef<HTMLInputElement>(null)

  function set<K extends keyof typeof EMPTY>(k: K, v: (typeof EMPTY)[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function handleClose(o: boolean) {
    if (!o) {
      setForm(EMPTY)
      if (fileRef.current) fileRef.current.value = ''
    }
    setOpen(o)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) return
    const fd = new FormData()
    fd.append('name', form.name)
    fd.append('address', form.address)
    fd.append('ssh_user', form.ssh_user)
    fd.append('ssh_port', String(form.ssh_port))
    fd.append('pve_node', form.pve_node)
    fd.append('ssh_key', file)
    addNode.mutate(fd, { onSuccess: () => handleClose(false) })
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('admin.proxmox')}</h1>
        <Button size="sm" onClick={() => setOpen(true)}>{t('admin.addProxmox')}</Button>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !nodes?.length && (
        <p className="text-muted-foreground">{t('admin.proxmoxEmpty')}</p>
      )}
      {nodes && nodes.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.name')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.address')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.sshUser')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.pveNode')}</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {nodes.map((n: ProxmoxNodeConfig) => (
                <tr key={n.name} className="border-b last:border-0">
                  <td className="px-4 py-2 font-medium">{n.name}</td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{n.address}</td>
                  <td className="px-4 py-2 text-muted-foreground">{n.ssh_user}</td>
                  <td className="px-4 py-2 text-muted-foreground">{n.pve_node}</td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => deleteNode.mutate(n.name)}
                      disabled={deleteNode.isPending}
                    >
                      {t('workspaces.actions.delete')}
                    </Button>
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
            <DialogTitle>{t('admin.addProxmox')}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="px-name">{t('admin.col.name')}</Label>
              <Input
                id="px-name"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="pve1"
                pattern="^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="px-address">{t('admin.form.address')}</Label>
              <Input
                id="px-address"
                value={form.address}
                onChange={(e) => set('address', e.target.value)}
                placeholder="192.168.10.10"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="px-user">{t('admin.form.sshUser')}</Label>
                <Input
                  id="px-user"
                  value={form.ssh_user}
                  onChange={(e) => set('ssh_user', e.target.value)}
                  placeholder="root"
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="px-port">{t('admin.form.sshPort')}</Label>
                <Input
                  id="px-port"
                  type="number"
                  value={form.ssh_port}
                  onChange={(e) => set('ssh_port', Number(e.target.value))}
                  min={1}
                  max={65535}
                  required
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="px-pvenode">{t('admin.form.pveNode')}</Label>
              <Input
                id="px-pvenode"
                value={form.pve_node}
                onChange={(e) => set('pve_node', e.target.value)}
                placeholder="pve"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="px-key">{t('admin.form.sshKey')}</Label>
              <input
                id="px-key"
                ref={fileRef}
                type="file"
                accept=".pem,.key,text/plain"
                required
                className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-md file:border file:border-input file:bg-transparent file:px-3 file:py-1 file:text-sm file:font-medium hover:file:bg-muted"
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => handleClose(false)}>
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={addNode.isPending}>
                {t('admin.form.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
