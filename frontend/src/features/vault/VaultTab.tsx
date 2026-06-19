import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Shield, Plus, Pencil } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import {
  useVaultKeys,
  useAddVaultKey,
  useDeleteVaultKey,
  useTestVaultKey,
  type VaultKey,
} from './api'

const DEFAULT_URL = 'https://vault.yoops.org'

function slugify(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+/, '')
    .replace(/-+$/, '')
    .slice(0, 31)
}

interface AddForm {
  label: string
  description: string
  apiKey: string
  url: string
}

interface EditForm {
  description: string
  apiKey: string
  url: string
}

const EMPTY_ADD: AddForm = { label: '', description: '', apiKey: '', url: DEFAULT_URL }

export default function VaultTab() {
  const { t } = useTranslation()
  const { data: keys = [], isLoading } = useVaultKeys()
  const addKey = useAddVaultKey()
  const deleteKey = useDeleteVaultKey()
  const testKey = useTestVaultKey()

  // ── Dialog ajouter ──────────────────────────────────────────────────
  const [addOpen, setAddOpen] = useState(false)
  const [addForm, setAddForm] = useState<AddForm>(EMPTY_ADD)

  // ── Dialog modifier ─────────────────────────────────────────────────
  const [editTarget, setEditTarget] = useState<VaultKey | null>(null)
  const [editForm, setEditForm] = useState<EditForm>({ description: '', apiKey: '', url: DEFAULT_URL })
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null)

  // ── Confirmation suppression ────────────────────────────────────────
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const addSlug = slugify(addForm.label)
  const canAdd = addSlug.length > 0 && addForm.apiKey.startsWith('hrpv_') && !addKey.isPending
  const canSaveEdit = editForm.apiKey.startsWith('hrpv_') && !(deleteKey.isPending || addKey.isPending)

  function openAdd() {
    setAddForm(EMPTY_ADD)
    setAddOpen(true)
  }

  function closeAdd() {
    setAddOpen(false)
    setAddForm(EMPTY_ADD)
    addKey.reset()
  }

  function openEdit(k: VaultKey) {
    setEditTarget(k)
    setEditForm({ description: k.description, apiKey: '', url: k.url })
    setTestResult(null)
    testKey.reset()
  }

  function closeEdit() {
    setEditTarget(null)
    testKey.reset()
  }

  function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!canAdd) return
    addKey.mutate(
      { identifier: addSlug, token: addForm.apiKey, url: addForm.url, description: addForm.description },
      { onSuccess: closeAdd },
    )
  }

  function handleEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editTarget || !canSaveEdit) return
    deleteKey.mutate(editTarget.identifier, {
      onSuccess: () =>
        addKey.mutate(
          { identifier: editTarget.identifier, token: editForm.apiKey, url: editForm.url, description: editForm.description },
          { onSuccess: closeEdit },
        ),
    })
  }

  function handleTest() {
    if (!editTarget) return
    setTestResult(null)
    testKey.mutate(editTarget.identifier, {
      onSuccess: (r) => setTestResult({ ok: true, text: `wallet: ${r.wallet_id.slice(0, 8)}…` }),
      onError: () => setTestResult({ ok: false, text: t('vault.testFailed') }),
    })
  }

  return (
    <div className="flex flex-col gap-6">

      {/* ── Bloc d'information ─────────────────────────────────────────── */}
      <div className="rounded-lg border bg-muted/40 p-5">
        <div className="mb-2 flex items-center gap-2">
          <Shield className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{t('vault.securityTitle')}</span>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">
          {t('vault.securityInfo')}
        </p>
        <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
          {t('vault.securityInfoVault')}{' '}
          <a
            href="https://vault.yoops.org"
            target="_blank"
            rel="noopener noreferrer"
            className="underline transition-colors hover:text-foreground"
          >
            vault.yoops.org
          </a>
        </p>
      </div>

      {/* ── Liste des clés ─────────────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">{t('vault.keys')}</h2>
          <Button size="sm" onClick={openAdd}>
            <Plus className="mr-1 h-4 w-4" />
            {t('vault.addKey')}
          </Button>
        </div>
        {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
        {!isLoading && keys.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('vault.noKeys')}</p>
        )}
        <div className="flex flex-col gap-2">
          {keys.map((k) => (
            <div
              key={k.identifier}
              className="flex items-center gap-3 rounded-lg border bg-card p-3"
            >
              <div className="min-w-0 flex-1">
                <span className="font-mono text-sm font-medium">{k.identifier}</span>
                {k.description && (
                  <p className="text-xs text-muted-foreground">{k.description}</p>
                )}
                <p className="font-mono text-xs text-muted-foreground opacity-60">{k.url}</p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => openEdit(k)}>
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              {confirmDelete === k.identifier ? (
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={deleteKey.isPending}
                    onClick={() =>
                      deleteKey.mutate(k.identifier, { onSuccess: () => setConfirmDelete(null) })
                    }
                  >
                    {t('vault.confirmDelete')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                    {t('common.cancel')}
                  </Button>
                </div>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setConfirmDelete(k.identifier)}
                >
                  {t('workspaces.actions.delete')}
                </Button>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── Dialog — Ajouter ───────────────────────────────────────────── */}
      <Dialog open={addOpen} onOpenChange={(o) => { if (!o) closeAdd() }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('vault.dialogAddTitle')}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleAdd} className="flex flex-col gap-3">
            <div className="flex gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="v-label">{t('vault.form.label')}</Label>
                <Input
                  id="v-label"
                  value={addForm.label}
                  onChange={(e) => setAddForm((f) => ({ ...f, label: e.target.value }))}
                  placeholder={t('vault.form.labelPlaceholder')}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <Label>{t('vault.form.slug')}</Label>
                <div className="flex h-9 items-center rounded-md border border-input bg-muted px-3 font-mono text-sm text-muted-foreground">
                  {addSlug || (
                    <span className="italic opacity-50">{t('vault.form.slugEmpty')}</span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="v-add-desc">{t('vault.form.description')}</Label>
              <Input
                id="v-add-desc"
                value={addForm.description}
                onChange={(e) => setAddForm((f) => ({ ...f, description: e.target.value }))}
                placeholder={t('vault.form.descriptionPlaceholder')}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="v-add-key">{t('vault.form.apiKey')}</Label>
              <Input
                id="v-add-key"
                type="password"
                value={addForm.apiKey}
                onChange={(e) => setAddForm((f) => ({ ...f, apiKey: e.target.value }))}
                placeholder="hrpv_1_…"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="v-add-url">{t('vault.form.url')}</Label>
              <Input
                id="v-add-url"
                value={addForm.url}
                onChange={(e) => setAddForm((f) => ({ ...f, url: e.target.value }))}
              />
            </div>
            {addKey.isError && (
              <Alert variant="destructive">
                <AlertDescription>
                  {addKey.error instanceof Error ? addKey.error.message : t('errors.generic')}
                </AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={closeAdd}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={!canAdd}>
                {addKey.isPending ? t('vault.form.saving') : t('vault.form.add')}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Dialog — Modifier ──────────────────────────────────────────── */}
      <Dialog open={editTarget !== null} onOpenChange={(o) => { if (!o) closeEdit() }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('vault.dialogEditTitle')}</DialogTitle>
          </DialogHeader>
          {editTarget && (
            <form onSubmit={handleEdit} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label>{t('vault.form.slug')}</Label>
                <div className="flex h-9 items-center rounded-md border border-input bg-muted px-3 font-mono text-sm text-muted-foreground">
                  {editTarget.identifier}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="v-edit-desc">{t('vault.form.description')}</Label>
                <Input
                  id="v-edit-desc"
                  value={editForm.description}
                  onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder={t('vault.form.descriptionPlaceholder')}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="v-edit-key">{t('vault.form.apiKey')}</Label>
                <div className="flex gap-2">
                  <Input
                    id="v-edit-key"
                    type="password"
                    value={editForm.apiKey}
                    onChange={(e) => setEditForm((f) => ({ ...f, apiKey: e.target.value }))}
                    placeholder="hrpv_1_…"
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleTest}
                    disabled={testKey.isPending}
                  >
                    {t('vault.test')}
                  </Button>
                </div>
                {testResult && (
                  <Badge
                    variant={testResult.ok ? 'secondary' : 'destructive'}
                    className="w-fit text-xs"
                  >
                    {testResult.text}
                  </Badge>
                )}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="v-edit-url">{t('vault.form.url')}</Label>
                <Input
                  id="v-edit-url"
                  value={editForm.url}
                  onChange={(e) => setEditForm((f) => ({ ...f, url: e.target.value }))}
                />
              </div>
              {(deleteKey.isError || addKey.isError) && (
                <Alert variant="destructive">
                  <AlertDescription>{t('errors.generic')}</AlertDescription>
                </Alert>
              )}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={closeEdit}>
                  {t('common.cancel')}
                </Button>
                <Button type="submit" disabled={!canSaveEdit}>
                  {deleteKey.isPending || addKey.isPending ? t('vault.form.saving') : t('common.save')}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

    </div>
  )
}
