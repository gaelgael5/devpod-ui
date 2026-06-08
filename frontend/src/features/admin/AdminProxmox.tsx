import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { HelpCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useAdminProxmox, type ProxmoxNodeConfig } from './useAdminProxmox'

const EMPTY = { name: '', address: '', ssh_user: 'root', ssh_port: 22, pve_node: 'pve', ssh_key_content: '' }

const SSH_KEYGEN_COMMANDS = `# Sur le serveur Proxmox, en tant que root :

# 1. Générer une paire de clés Ed25519 dédiée au portail
ssh-keygen -t ed25519 -f /root/.ssh/portal_key -N ""

# 2. Autoriser la clé publique sur ce serveur
cat /root/.ssh/portal_key.pub >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# 3. Afficher la clé privée — copiez tout ce bloc dans le portail
cat /root/.ssh/portal_key`

export default function AdminProxmox() {
  const { t } = useTranslation()
  const { nodesQuery, deleteNode, addNode } = useAdminProxmox()
  const { data: nodes, isLoading, isError } = nodesQuery
  const [open, setOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const fileRef = useRef<HTMLInputElement>(null)

  function set<K extends keyof typeof EMPTY>(k: K, v: (typeof EMPTY)[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function handleClose(o: boolean) {
    if (!o) setForm(EMPTY)
    setOpen(o)
  }

  function handleFileLoad(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => set('ssh_key_content', (ev.target?.result as string) ?? '')
    reader.readAsText(file)
    e.target.value = ''
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const content = form.ssh_key_content.trim()
    if (!content) return
    const fd = new FormData()
    fd.append('name', form.name)
    fd.append('address', form.address)
    fd.append('ssh_user', form.ssh_user)
    fd.append('ssh_port', String(form.ssh_port))
    fd.append('pve_node', form.pve_node)
    fd.append('ssh_key', new Blob([content], { type: 'text/plain' }), 'id_ed25519')
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

      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('admin.form.sshKeyHelp')}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t('admin.form.sshKeyHelpIntro')}</p>
          <pre className="overflow-x-auto rounded-md bg-muted px-4 py-3 text-xs leading-relaxed">
            {SSH_KEYGEN_COMMANDS}
          </pre>
          <p className="text-sm text-muted-foreground">{t('admin.form.sshKeyHelpNote')}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setHelpOpen(false)}>{t('workspaces.confirm.cancel')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
              <div className="flex items-center justify-between">
                <Label htmlFor="px-key">{t('admin.form.sshKey')}</Label>
                <button
                  type="button"
                  onClick={() => setHelpOpen(true)}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                >
                  <HelpCircle size={13} />
                  {t('admin.form.sshKeyHelp')}
                </button>
              </div>
              <textarea
                id="px-key"
                value={form.ssh_key_content}
                onChange={(e) => set('ssh_key_content', e.target.value)}
                placeholder={t('admin.form.sshKeyPlaceholder')}
                rows={5}
                required
                className="min-h-[100px] w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-sm focus:outline-none focus:ring-1 focus:ring-ring resize-y"
              />
              <div className="flex items-center gap-2">
                <input ref={fileRef} type="file" accept=".pem,.key,text/plain" className="hidden" onChange={handleFileLoad} />
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                >
                  {t('admin.form.sshKeyLoadFile')}
                </button>
              </div>
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
