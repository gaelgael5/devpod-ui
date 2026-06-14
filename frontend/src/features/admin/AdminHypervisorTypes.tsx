import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useAdminHypervisorTypes, type HypervisorTypeConfig } from './useAdminHypervisorTypes'

const EMPTY: HypervisorTypeConfig = { label: '', name: '', add_script: '', destroy_script: '' }

function labelToKey(label: string): string {
  return label
    .replace(/[^a-z0-9-]/g, '')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

export default function AdminHypervisorTypes() {
  const { t } = useTranslation()
  const { typesQuery, addType, updateType, deleteType } = useAdminHypervisorTypes()
  const { data: types, isLoading, isError } = typesQuery

  const [open, setOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<HypervisorTypeConfig | null>(null)
  const [form, setForm] = useState<HypervisorTypeConfig>(EMPTY)
  const [editForm, setEditForm] = useState<Omit<HypervisorTypeConfig, 'name'>>({
    label: '',
    add_script: '',
    destroy_script: '',
  })

  function handleClose(o: boolean) {
    if (!o) setForm(EMPTY)
    setOpen(o)
  }

  function handleEditOpen(ht: HypervisorTypeConfig) {
    setEditTarget(ht)
    setEditForm({ label: ht.label, add_script: ht.add_script, destroy_script: ht.destroy_script })
    setEditOpen(true)
  }

  function handleEditClose(o: boolean) {
    if (!o) setEditTarget(null)
    setEditOpen(o)
  }

  function handleLabelChange(label: string) {
    setForm((f) => ({ ...f, label, name: labelToKey(label) }))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    addType.mutate(form, { onSuccess: () => handleClose(false) })
  }

  function handleEditSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!editTarget) return
    updateType.mutate(
      { name: editTarget.name, body: editForm },
      { onSuccess: () => handleEditClose(false) },
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('admin.hypervisorTypes')}</h1>
        <Button size="sm" onClick={() => setOpen(true)}>{t('admin.addHypervisorType')}</Button>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !types?.length && (
        <p className="text-muted-foreground">{t('admin.hypervisorTypesEmpty')}</p>
      )}
      {types && types.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.form.hypervisorLabel')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.name')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.form.addScript')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.form.destroyScript')}</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {types.map((ht) => (
                <tr key={ht.name} className="border-b last:border-0">
                  <td className="px-4 py-2 font-medium">{ht.label || '—'}</td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{ht.name}</td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground truncate max-w-xs">{ht.add_script || '—'}</td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground truncate max-w-xs">{ht.destroy_script || '—'}</td>
                  <td className="px-4 py-2 text-right flex items-center justify-end gap-1">
                    <Button size="sm" variant="ghost" onClick={() => handleEditOpen(ht)}>
                      {t('workspaces.actions.edit')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => deleteType.mutate(ht.name)}
                      disabled={deleteType.isPending}
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

      {/* ─── Dialogue ajout ───────────────────────────────────────────────── */}
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.addHypervisorType')}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ht-label">{t('admin.form.hypervisorLabel')}</Label>
              <Input
                id="ht-label"
                value={form.label}
                onChange={(e) => handleLabelChange(e.target.value)}
                placeholder="Proxmox KVM"
                autoFocus
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ht-name">{t('admin.col.name')}</Label>
              <Input
                id="ht-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="proxmox-kvm"
                pattern="^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$"
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ht-add">{t('admin.form.addScript')}</Label>
              <Input
                id="ht-add"
                type="url"
                value={form.add_script}
                onChange={(e) => setForm((f) => ({ ...f, add_script: e.target.value }))}
                placeholder="https://exemple.com/scripts/create-vm.json"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ht-destroy">{t('admin.form.destroyScript')}</Label>
              <Input
                id="ht-destroy"
                type="url"
                value={form.destroy_script}
                onChange={(e) => setForm((f) => ({ ...f, destroy_script: e.target.value }))}
                placeholder="https://exemple.com/scripts/destroy-vm.json"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => handleClose(false)}>
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={addType.isPending}>
                {t('admin.form.save')}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* ─── Dialogue édition ─────────────────────────────────────────────── */}
      <Dialog open={editOpen} onOpenChange={handleEditClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.editHypervisorType')} — {editTarget?.name}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleEditSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="eht-label">{t('admin.form.hypervisorLabel')}</Label>
              <Input
                id="eht-label"
                value={editForm.label}
                onChange={(e) => setEditForm((f) => ({ ...f, label: e.target.value }))}
                placeholder="Proxmox KVM"
                autoFocus
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="eht-add">{t('admin.form.addScript')}</Label>
              <Input
                id="eht-add"
                type="url"
                value={editForm.add_script}
                onChange={(e) => setEditForm((f) => ({ ...f, add_script: e.target.value }))}
                placeholder="https://exemple.com/scripts/create-vm.json"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="eht-destroy">{t('admin.form.destroyScript')}</Label>
              <Input
                id="eht-destroy"
                type="url"
                value={editForm.destroy_script}
                onChange={(e) => setEditForm((f) => ({ ...f, destroy_script: e.target.value }))}
                placeholder="https://exemple.com/scripts/destroy-vm.json"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => handleEditClose(false)}>
                {t('workspaces.confirm.cancel')}
              </Button>
              <Button type="submit" disabled={updateType.isPending}>
                {t('admin.form.save')}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
