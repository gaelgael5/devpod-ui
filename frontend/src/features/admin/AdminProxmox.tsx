import { useCallback, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy, HelpCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useAdminProxmox, type ProxmoxNodeConfig } from './useAdminProxmox'

const EMPTY = { name: '', address: '', ssh_user: 'root', ssh_port: 22, pve_node: 'pve', ssh_key_content: '' }

const SSH_STEPS = [
  {
    label: 'Generate a dedicated Ed25519 key pair for the portal',
    cmd: 'ssh-keygen -t ed25519 -f /root/.ssh/portal_key -N ""',
  },
  {
    label: 'Authorize the public key on this server',
    cmd: 'cat /root/.ssh/portal_key.pub >> /root/.ssh/authorized_keys\nchmod 600 /root/.ssh/authorized_keys',
  },
  {
    label: 'Display the private key — paste the output into the portal',
    cmd: 'cat /root/.ssh/portal_key',
  },
]

export default function AdminProxmox() {
  const { t } = useTranslation()
  const { nodesQuery, deleteNode, addNode } = useAdminProxmox()
  const { data: nodes, isLoading, isError } = nodesQuery
  const [open, setOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const [form, setForm] = useState(EMPTY)
  const fileRef = useRef<HTMLInputElement>(null)
  // Textarea caché dans le dialog pour le fallback execCommand
  // (doit être dans le dialog pour ne pas être bloqué par le focus trap Radix)
  const copyFallbackRef = useRef<HTMLTextAreaElement>(null)

  const copyCmd = useCallback((cmd: string, index: number) => {
    const markDone = () => {
      setCopiedIndex(index)
      setTimeout(() => setCopiedIndex((c) => (c === index ? null : c)), 1500)
    }
    const legacyCopy = () => {
      const ta = copyFallbackRef.current
      if (!ta) return
      ta.value = cmd
      ta.focus()
      ta.select()
      try { document.execCommand('copy'); markDone() } catch { /* ignore */ }
    }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(cmd).then(markDone, legacyCopy)
    } else {
      legacyCopy()
    }
  }, [])

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
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>SSH key setup — Proxmox server (root)</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Run these commands on the Proxmox server, then paste the output of step 3 into the private key field.
          </p>
          <div className="flex flex-col gap-3">
            {SSH_STEPS.map((step, i) => (
              <div key={i} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">
                  {i + 1}. {step.label}
                </span>
                <div className="flex items-start gap-2 rounded-md bg-muted px-3 py-2">
                  <pre className="flex-1 overflow-x-auto text-xs leading-relaxed">{step.cmd}</pre>
                  <button
                    type="button"
                    onClick={() => copyCmd(step.cmd, i)}
                    className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground transition-colors"
                    title="Copy"
                  >
                    {copiedIndex === i ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                  </button>
                </div>
              </div>
            ))}
          </div>
          {/* textarea caché pour le fallback execCommand — doit rester dans le dialog */}
          <textarea
            ref={copyFallbackRef}
            aria-hidden="true"
            tabIndex={-1}
            readOnly
            style={{ position: 'absolute', opacity: 0, pointerEvents: 'none', width: 0, height: 0 }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setHelpOpen(false)}>Close</Button>
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
