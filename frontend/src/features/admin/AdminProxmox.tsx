import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, CircleCheck, CircleX, Copy, HelpCircle, LoaderCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { apiFetchJson } from '@/shared/api/client'
import { useAdminProxmox, type ProxmoxNodeConfig } from './useAdminProxmox'

const EMPTY = { name: '', address: '', ssh_user: 'root', ssh_port: 22, pve_node: 'pve', script_url: '', ssh_key_content: '' }
type AddForm = typeof EMPTY
type EditForm = { address: string; ssh_user: string; ssh_port: number; pve_node: string; script_url: string; ssh_key_content: string }
type TestStatus = 'idle' | 'testing' | 'ok' | 'error'

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
  const { nodesQuery, deleteNode, addNode, updateNode } = useAdminProxmox()
  const { data: nodes, isLoading, isError } = nodesQuery

  const [open, setOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<ProxmoxNodeConfig | null>(null)

  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const [form, setForm] = useState<AddForm>(EMPTY)
  const [editForm, setEditForm] = useState<EditForm>({ address: '', ssh_user: 'root', ssh_port: 22, pve_node: 'pve', script_url: '', ssh_key_content: '' })

  const [addTestStatus, setAddTestStatus] = useState<TestStatus>('idle')
  const [addTestError, setAddTestError] = useState<string | null>(null)
  const [editTestStatus, setEditTestStatus] = useState<TestStatus>('idle')
  const [editTestError, setEditTestError] = useState<string | null>(null)

  const fileRef = useRef<HTMLInputElement>(null)
  const editFileRef = useRef<HTMLInputElement>(null)

  function copyCmd(cmd: string, index: number) {
    const markDone = () => {
      setCopiedIndex(index)
      setTimeout(() => setCopiedIndex((c) => (c === index ? null : c)), 1500)
    }

    const rangeCopy = () => {
      const el = document.querySelector<HTMLElement>(`[data-step="${index}"]`)
      if (!el) return
      try {
        const range = document.createRange()
        range.selectNodeContents(el)
        const sel = window.getSelection()
        sel?.removeAllRanges()
        sel?.addRange(range)
        document.execCommand('copy')
        sel?.removeAllRanges()
        markDone()
      } catch { /* ignore */ }
    }

    if (window.isSecureContext && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(cmd).then(markDone).catch(rangeCopy)
    } else {
      rangeCopy()
    }
  }

  function setField<K extends keyof AddForm>(k: K, v: AddForm[K]) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function setEditField<K extends keyof EditForm>(k: K, v: EditForm[K]) {
    setEditForm((f) => ({ ...f, [k]: v }))
  }

  function handleClose(o: boolean) {
    if (!o) {
      setForm(EMPTY)
      setAddTestStatus('idle')
      setAddTestError(null)
    }
    setOpen(o)
  }

  function handleEditOpen(node: ProxmoxNodeConfig) {
    setEditTarget(node)
    setEditForm({
      address: node.address,
      ssh_user: node.ssh_user,
      ssh_port: node.ssh_port,
      pve_node: node.pve_node,
      script_url: node.script_url,
      ssh_key_content: '',
    })
    setEditTestStatus('idle')
    setEditTestError(null)
    setEditOpen(true)
  }

  function handleEditClose(o: boolean) {
    if (!o) {
      setEditTarget(null)
      setEditTestStatus('idle')
      setEditTestError(null)
    }
    setEditOpen(o)
  }

  function handleFileLoad(e: React.ChangeEvent<HTMLInputElement>, setter: (v: string) => void) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => setter((ev.target?.result as string) ?? '')
    reader.readAsText(file)
    e.target.value = ''
  }

  async function handleTestAdd() {
    const content = form.ssh_key_content.trim()
    if (!form.address || !content) return
    setAddTestStatus('testing')
    setAddTestError(null)
    try {
      const fd = new FormData()
      fd.append('address', form.address)
      fd.append('ssh_user', form.ssh_user)
      fd.append('ssh_port', String(form.ssh_port))
      fd.append('ssh_key', new Blob([content], { type: 'text/plain' }), 'id_ed25519')
      const res = await apiFetchJson<{ ok: boolean; error: string | null }>(
        '/admin/proxmox/test-connection',
        { method: 'POST', body: fd },
      )
      setAddTestStatus(res.ok ? 'ok' : 'error')
      setAddTestError(res.error ?? null)
    } catch (e) {
      setAddTestStatus('error')
      setAddTestError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleTestEdit() {
    if (!editTarget) return
    setEditTestStatus('testing')
    setEditTestError(null)
    try {
      const res = await apiFetchJson<{ ok: boolean; error: string | null }>(
        `/admin/proxmox/${editTarget.name}/ping`,
      )
      setEditTestStatus(res.ok ? 'ok' : 'error')
      setEditTestError(res.error ?? null)
    } catch (e) {
      setEditTestStatus('error')
      setEditTestError(e instanceof Error ? e.message : String(e))
    }
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
    fd.append('script_url', form.script_url)
    fd.append('ssh_key', new Blob([content], { type: 'text/plain' }), 'id_ed25519')
    addNode.mutate(fd, { onSuccess: () => handleClose(false) })
  }

  function handleEditSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!editTarget) return
    const fd = new FormData()
    fd.append('address', editForm.address)
    fd.append('ssh_user', editForm.ssh_user)
    fd.append('ssh_port', String(editForm.ssh_port))
    fd.append('pve_node', editForm.pve_node)
    fd.append('script_url', editForm.script_url)
    const keyContent = editForm.ssh_key_content.trim()
    if (keyContent) {
      fd.append('ssh_key', new Blob([keyContent], { type: 'text/plain' }), 'id_ed25519')
    }
    updateNode.mutate({ name: editTarget.name, fd }, { onSuccess: () => handleEditClose(false) })
  }

  function renderTestStatus(status: TestStatus, error: string | null) {
    if (status === 'idle') return null
    if (status === 'testing') return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <LoaderCircle size={12} className="animate-spin" />
        {t('admin.form.testing')}
      </p>
    )
    if (status === 'ok') return (
      <p className="flex items-center gap-1.5 text-xs text-green-600">
        <CircleCheck size={12} />
        {t('admin.form.testOk')}
      </p>
    )
    return (
      <p className="flex items-center gap-1.5 text-xs text-destructive">
        <CircleX size={12} />
        {error ?? t('admin.form.testFailed')}
      </p>
    )
  }

  const sshKeyArea = (
    value: string,
    onChange: (v: string) => void,
    fileInputRef: React.RefObject<HTMLInputElement | null>,
    optional = false,
  ) => (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <Label htmlFor="px-key">
          {t('admin.form.sshKey')}
          {optional && <span className="ml-1 text-xs text-muted-foreground">({t('admin.form.sshKeyOptional')})</span>}
        </Label>
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
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t('admin.form.sshKeyPlaceholder')}
        rows={5}
        required={!optional}
        className="min-h-[100px] w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-sm focus:outline-none focus:ring-1 focus:ring-ring resize-y"
      />
      <div className="flex items-center gap-2">
        <input ref={fileInputRef} type="file" accept=".pem,.key,text/plain" className="hidden" onChange={(e) => handleFileLoad(e, onChange)} />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
        >
          {t('admin.form.sshKeyLoadFile')}
        </button>
      </div>
    </div>
  )

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
                  <td className="px-4 py-2 text-right flex items-center justify-end gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleEditOpen(n)}
                    >
                      {t('workspaces.actions.edit')}
                    </Button>
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

      {/* ─── Dialogue aide clé SSH ─────────────────────────────────────────── */}
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
                  <pre data-step={i} className="flex-1 overflow-x-auto text-xs leading-relaxed">{step.cmd}</pre>
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
          <DialogFooter>
            <Button variant="outline" onClick={() => setHelpOpen(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Dialogue ajout ───────────────────────────────────────────────── */}
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
                onChange={(e) => setField('name', e.target.value)}
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
                onChange={(e) => setField('address', e.target.value)}
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
                  onChange={(e) => setField('ssh_user', e.target.value)}
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
                  onChange={(e) => setField('ssh_port', Number(e.target.value))}
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
                onChange={(e) => setField('pve_node', e.target.value)}
                placeholder="pve"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="px-scripturl">{t('admin.form.scriptUrl')}</Label>
              <Input
                id="px-scripturl"
                type="url"
                value={form.script_url}
                onChange={(e) => setField('script_url', e.target.value)}
                placeholder={t('admin.form.scriptUrlPlaceholder')}
              />
            </div>
            {sshKeyArea(form.ssh_key_content, (v) => setField('ssh_key_content', v), fileRef)}
            {renderTestStatus(addTestStatus, addTestError)}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={handleTestAdd}
                disabled={addTestStatus === 'testing' || !form.address || !form.ssh_key_content.trim()}
              >
                {addTestStatus === 'testing'
                  ? <LoaderCircle size={14} className="mr-1.5 animate-spin" />
                  : null}
                {t('admin.form.testConnection')}
              </Button>
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

      {/* ─── Dialogue édition ─────────────────────────────────────────────── */}
      <Dialog open={editOpen} onOpenChange={handleEditClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.editProxmox')} — {editTarget?.name}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleEditSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ep-address">{t('admin.form.address')}</Label>
              <Input
                id="ep-address"
                value={editForm.address}
                onChange={(e) => setEditField('address', e.target.value)}
                placeholder="192.168.10.10"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="ep-user">{t('admin.form.sshUser')}</Label>
                <Input
                  id="ep-user"
                  value={editForm.ssh_user}
                  onChange={(e) => setEditField('ssh_user', e.target.value)}
                  placeholder="root"
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="ep-port">{t('admin.form.sshPort')}</Label>
                <Input
                  id="ep-port"
                  type="number"
                  value={editForm.ssh_port}
                  onChange={(e) => setEditField('ssh_port', Number(e.target.value))}
                  min={1}
                  max={65535}
                  required
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ep-pvenode">{t('admin.form.pveNode')}</Label>
              <Input
                id="ep-pvenode"
                value={editForm.pve_node}
                onChange={(e) => setEditField('pve_node', e.target.value)}
                placeholder="pve"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ep-scripturl">{t('admin.form.scriptUrl')}</Label>
              <Input
                id="ep-scripturl"
                type="url"
                value={editForm.script_url}
                onChange={(e) => setEditField('script_url', e.target.value)}
                placeholder={t('admin.form.scriptUrlPlaceholder')}
              />
            </div>
            {sshKeyArea(editForm.ssh_key_content, (v) => setEditField('ssh_key_content', v), editFileRef, true)}
            {renderTestStatus(editTestStatus, editTestError)}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={handleTestEdit}
                disabled={editTestStatus === 'testing'}
              >
                {editTestStatus === 'testing'
                  ? <LoaderCircle size={14} className="mr-1.5 animate-spin" />
                  : null}
                {t('admin.form.testConnection')}
              </Button>
              <Button type="button" variant="outline" onClick={() => handleEditClose(false)}>
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={updateNode.isPending}>
                {t('admin.form.save')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
