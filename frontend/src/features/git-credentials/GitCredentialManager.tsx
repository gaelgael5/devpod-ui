import { useState, useEffect, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, KeyRound, Eye, EyeOff, Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  useGitCredentials,
  useAddGitCredential,
  useDeleteGitCredential,
  useUpdateGitCredential,
  useGitCredentialPublicKey,
  type GitCredentialSummary,
  type UpdateCredentialPayload,
} from './useGitCredentials'
import GitCredentialPublicKeyDialog from './GitCredentialPublicKeyDialog'

const KNOWN_HOSTS = [
  { value: 'github.com', labelKey: 'gitCredentials.hosts.github' },
  { value: 'gitlab.com', labelKey: 'gitCredentials.hosts.gitlab' },
  { value: 'bitbucket.org', labelKey: 'gitCredentials.hosts.bitbucket' },
  { value: 'dev.azure.com', labelKey: 'gitCredentials.hosts.azure' },
  { value: 'codeberg.org', labelKey: 'gitCredentials.hosts.codeberg' },
  { value: '__other__', labelKey: 'gitCredentials.hosts.other' },
] as const

type KnownHostValue = (typeof KNOWN_HOSTS)[number]['value']

const EMPTY_FORM = {
  name: '',
  hostSelect: 'github.com' as KnownHostValue,
  hostCustom: '',
  kind: 'token' as 'ssh' | 'token',
  username: '',
  token: '',
  privateKey: '',
}

const SENTINEL = '••••••••'

type EditFormState = {
  name: string
  hostSelect: KnownHostValue
  hostCustom: string
  kind: 'ssh' | 'token'
  username: string
  tokenValue: string
  tokenTouched: boolean
  privateKey: string
  keyTouched: boolean
}

function toHostSelect(host: string): KnownHostValue {
  const known = KNOWN_HOSTS.find(h => h.value !== '__other__' && h.value === host)
  return known ? (known.value as KnownHostValue) : '__other__'
}

function initEditForm(c: GitCredentialSummary): EditFormState {
  return {
    name: c.name,
    hostSelect: toHostSelect(c.host),
    hostCustom: c.host,
    kind: c.kind,
    username: c.username,
    tokenValue: SENTINEL,
    tokenTouched: false,
    privateKey: '',
    keyTouched: false,
  }
}

export default function GitCredentialManager() {
  const { t } = useTranslation()
  const { data: credentials, isError } = useGitCredentials()
  const addMutation = useAddGitCredential()
  const deleteMutation = useDeleteGitCredential()
  const updateMutation = useUpdateGitCredential()

  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [showToken, setShowToken] = useState(false)
  const [formError, setFormError] = useState('')
  const [toDelete, setToDelete] = useState<GitCredentialSummary | null>(null)
  const [toEdit, setToEdit] = useState<GitCredentialSummary | null>(null)
  const [editForm, setEditForm] = useState<EditFormState | null>(null)
  const [editError, setEditError] = useState('')
  const [publicKeyDialog, setPublicKeyDialog] = useState<{ name: string; key: string } | null>(null)
  const [publicKeyFetchName, setPublicKeyFetchName] = useState<string | null>(null)

  const publicKeyQuery = useGitCredentialPublicKey(publicKeyFetchName ?? '', !!publicKeyFetchName)

  useEffect(() => {
    if (publicKeyQuery.isSuccess && publicKeyFetchName && publicKeyQuery.data) {
      setPublicKeyDialog({ name: publicKeyFetchName, key: publicKeyQuery.data.public_key })
      setPublicKeyFetchName(null)
    }
  }, [publicKeyQuery.isSuccess, publicKeyQuery.data, publicKeyFetchName])

  useEffect(() => {
    if (publicKeyQuery.isError && publicKeyFetchName) {
      setPublicKeyFetchName(null)
    }
  }, [publicKeyQuery.isError, publicKeyFetchName])

  const credentialList: GitCredentialSummary[] = credentials ?? []
  const effectiveHost =
    form.hostSelect === '__other__' ? form.hostCustom.trim() : form.hostSelect

  function resetForm() {
    setForm(EMPTY_FORM)
    setShowToken(false)
    setFormError('')
    setShowForm(false)
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError('')

    const payload = {
      name: form.name.trim(),
      host: effectiveHost,
      kind: form.kind,
      username: form.username.trim() || undefined,
      token: form.kind === 'token' ? form.token.trim() : undefined,
      private_key: form.kind === 'ssh' ? form.privateKey : undefined,
    }

    addMutation.mutate(payload, {
      onSuccess: () => resetForm(),
      onError: (err: unknown) =>
        setFormError(err instanceof Error ? err.message : t('gitCredentials.errors.add')),
    })
  }

  function handleDelete() {
    if (!toDelete) return
    deleteMutation.mutate(toDelete.name, {
      onSuccess: () => setToDelete(null),
    })
  }

  function handleGenerate() {
    setFormError('')
    addMutation.mutate(
      { name: form.name.trim(), host: effectiveHost, kind: 'ssh', generate_key: true, private_key: '' },
      {
        onSuccess: data => {
          if (data.public_key) {
            setPublicKeyDialog({ name: data.name, key: data.public_key })
          }
          resetForm()
        },
        onError: (err: unknown) =>
          setFormError(err instanceof Error ? err.message : t('gitCredentials.errors.add')),
      },
    )
  }

  function openEdit(c: GitCredentialSummary) {
    setToEdit(c)
    setEditForm(initEditForm(c))
    setEditError('')
    setShowToken(false)
  }

  function closeEdit() {
    setToEdit(null)
    setEditForm(null)
    setEditError('')
    setShowToken(false)
  }

  function handleEditKindChange(newKind: 'ssh' | 'token') {
    setEditForm(f =>
      f
        ? {
            ...f,
            kind: newKind,
            tokenValue: '',
            tokenTouched: newKind === 'token',
            privateKey: '',
            keyTouched: newKind === 'ssh',
          }
        : f,
    )
  }

  function handleEditSubmit(e: FormEvent) {
    e.preventDefault()
    if (!toEdit || !editForm) return
    setEditError('')

    const effectiveHost =
      editForm.hostSelect === '__other__' ? editForm.hostCustom.trim() : editForm.hostSelect

    const payload: UpdateCredentialPayload = {
      host: effectiveHost,
      kind: editForm.kind,
    }
    if (editForm.name.trim() !== toEdit.name) payload.new_name = editForm.name.trim()
    if (editForm.kind === 'token') {
      payload.username = editForm.username.trim()
      payload.token = editForm.tokenTouched ? editForm.tokenValue : '__UNCHANGED__'
    } else {
      payload.private_key = editForm.keyTouched ? editForm.privateKey : '__UNCHANGED__'
    }

    updateMutation.mutate(
      { name: toEdit.name, payload },
      {
        onSuccess: () => closeEdit(),
        onError: (err: unknown) =>
          setEditError(err instanceof Error ? err.message : t('gitCredentials.errors.update')),
      },
    )
  }

  return (
    <div className="max-w-2xl">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('gitCredentials.title')}</h1>
        <Button size="sm" onClick={() => setShowForm(true)} disabled={showForm}>
          <Plus className="mr-1.5 h-4 w-4" />
          {t('gitCredentials.add')}
        </Button>
      </div>

      {isError && (
        <p className="mb-4 text-sm text-destructive">{t('gitCredentials.errors.load')}</p>
      )}

      {/* ── Formulaire d'ajout ───────────────────────────────────────── */}
      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 rounded-lg border bg-card p-4 flex flex-col gap-4"
        >
          <h2 className="font-medium">{t('gitCredentials.add')}</h2>

          {/* Nom */}
          <div>
            <Label htmlFor="cred-name" className="text-xs">{t('gitCredentials.name')}</Label>
            <Input
              id="cred-name"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder={t('gitCredentials.namePlaceholder')}
              className="mt-1"
              required
            />
            <p className="mt-1 text-xs text-muted-foreground">{t('gitCredentials.nameHint')}</p>
          </div>

          {/* Hôte */}
          <div>
            <Label className="text-xs">{t('gitCredentials.host')}</Label>
            <Select
              value={form.hostSelect}
              onValueChange={v => setForm(f => ({ ...f, hostSelect: v as KnownHostValue }))}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KNOWN_HOSTS.map(h => (
                  <SelectItem key={h.value} value={h.value}>
                    {t(h.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {form.hostSelect === '__other__' && (
              <Input
                value={form.hostCustom}
                onChange={e => setForm(f => ({ ...f, hostCustom: e.target.value }))}
                placeholder="git.example.com"
                className="mt-2"
                required
              />
            )}
          </div>

          {/* Type d'authentification */}
          <div>
            <Label className="text-xs">{t('gitCredentials.kind')}</Label>
            <Select
              value={form.kind}
              onValueChange={v => setForm(f => ({ ...f, kind: v as 'ssh' | 'token' }))}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="token">{t('gitCredentials.kindPat')}</SelectItem>
                <SelectItem value="ssh">{t('gitCredentials.kindSsh')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Champs PAT */}
          {form.kind === 'token' && (
            <>
              <div>
                <Label htmlFor="cred-username" className="text-xs">
                  {t('gitCredentials.username')}
                </Label>
                <Input
                  id="cred-username"
                  value={form.username}
                  onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                  placeholder={t('gitCredentials.usernamePlaceholder')}
                  className="mt-1"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  {t('gitCredentials.usernameHint')}
                </p>
              </div>
              <div>
                <Label htmlFor="cred-token" className="text-xs">{t('gitCredentials.token')}</Label>
                <div className="relative mt-1">
                  <Input
                    id="cred-token"
                    type={showToken ? 'text' : 'password'}
                    value={form.token}
                    onChange={e => setForm(f => ({ ...f, token: e.target.value }))}
                    placeholder={t('gitCredentials.tokenPlaceholder')}
                    className="pr-9"
                    required
                  />
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={() => setShowToken(v => !v)}
                    tabIndex={-1}
                  >
                    {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
            </>
          )}

          {/* Champs SSH */}
          {form.kind === 'ssh' && (
            <div>
              <Label htmlFor="cred-key" className="text-xs">
                {t('gitCredentials.privateKey')}
              </Label>
              <Textarea
                id="cred-key"
                value={form.privateKey}
                onChange={e => setForm(f => ({ ...f, privateKey: e.target.value }))}
                placeholder={t('gitCredentials.privateKeyPlaceholder')}
                className="mt-1 font-mono text-xs"
                rows={6}
              />
              <div className="mt-1.5">
                <input
                  type="file"
                  accept=".pem,.key"
                  id="cred-key-file"
                  className="hidden"
                  onChange={e => {
                    const file = e.target.files?.[0]
                    if (!file) return
                    const reader = new FileReader()
                    reader.onload = ev =>
                      setForm(f => ({ ...f, privateKey: (ev.target?.result as string) ?? '' }))
                    reader.readAsText(file)
                    e.target.value = ''
                  }}
                />
                <Button type="button" variant="outline" size="sm" asChild>
                  <label htmlFor="cred-key-file" className="cursor-pointer">
                    {t('gitCredentials.loadKeyFile')}
                  </label>
                </Button>
              </div>
            </div>
          )}

          {formError && (
            <p role="alert" className="text-xs text-destructive">{formError}</p>
          )}

          <div className="flex gap-2 justify-end">
            <Button type="button" variant="ghost" size="sm" onClick={resetForm}>
              {t('gitCredentials.cancel')}
            </Button>
            {form.kind === 'ssh' && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={!form.name.trim() || !effectiveHost || addMutation.isPending}
                onClick={handleGenerate}
              >
                {addMutation.isPending ? '…' : t('gitCredentials.generateKey')}
              </Button>
            )}
            <Button type="submit" size="sm" disabled={addMutation.isPending}>
              {addMutation.isPending ? '…' : t('gitCredentials.save')}
            </Button>
          </div>
        </form>
      )}

      {/* ── Liste des credentials ────────────────────────────────────── */}
      {credentialList.length === 0 && !showForm && (
        <p className="text-sm text-muted-foreground">{t('gitCredentials.empty')}</p>
      )}

      <div className="flex flex-col gap-2">
        {credentialList.map((c: GitCredentialSummary) => (
          <div
            key={c.name}
            className="flex items-center justify-between rounded-lg border bg-card px-4 py-3"
          >
            <div className="flex items-center gap-3">
              <KeyRound className="h-4 w-4 text-muted-foreground shrink-0" />
              <div>
                <div className="font-medium text-sm">{c.name}</div>
                <div className="text-xs text-muted-foreground">{c.host}</div>
              </div>
              <Badge variant="secondary" className="text-xs">
                {c.kind === 'token' ? 'PAT' : 'SSH'}
              </Badge>
            </div>
            <div className="flex items-center gap-1">
              {c.kind === 'ssh' && (
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  onClick={() => setPublicKeyFetchName(c.name)}
                  aria-label={t('gitCredentials.viewPublicKey')}
                  disabled={publicKeyFetchName === c.name}
                >
                  <KeyRound className="h-4 w-4" />
                </Button>
              )}
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={() => openEdit(c)}
                aria-label={t('gitCredentials.edit')}
              >
                <Pencil className="h-4 w-4" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8 text-destructive hover:text-destructive"
                onClick={() => setToDelete(c)}
                aria-label={t('gitCredentials.delete')}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* ── Dialog de confirmation de suppression ───────────────────── */}
      <Dialog open={!!toDelete} onOpenChange={open => { if (!open) setToDelete(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t('gitCredentials.deleteConfirm', { name: toDelete?.name ?? '' })}
            </DialogTitle>
            <DialogDescription>{t('gitCredentials.deleteDescription')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setToDelete(null)}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? '…' : t('gitCredentials.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Dialog d'édition ────────────────────────────────────────── */}
      <Dialog open={!!toEdit} onOpenChange={open => { if (!open) closeEdit() }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('gitCredentials.editDialogTitle')}</DialogTitle>
          </DialogHeader>

          {editForm && (
            <form onSubmit={handleEditSubmit} className="flex flex-col gap-4 pt-2">
              {/* Nom */}
              <div>
                <Label htmlFor="edit-cred-name" className="text-xs">{t('gitCredentials.name')}</Label>
                <Input
                  id="edit-cred-name"
                  value={editForm.name}
                  onChange={e => setEditForm(f => f ? { ...f, name: e.target.value } : f)}
                  className="mt-1"
                  required
                />
              </div>

              {/* Hôte */}
              <div>
                <Label className="text-xs">{t('gitCredentials.host')}</Label>
                <Select
                  value={editForm.hostSelect}
                  onValueChange={v => setEditForm(f => f ? { ...f, hostSelect: v as KnownHostValue } : f)}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {KNOWN_HOSTS.map(h => (
                      <SelectItem key={h.value} value={h.value}>
                        {t(h.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {editForm.hostSelect === '__other__' && (
                  <Input
                    value={editForm.hostCustom}
                    onChange={e => setEditForm(f => f ? { ...f, hostCustom: e.target.value } : f)}
                    placeholder="git.example.com"
                    className="mt-2"
                    required
                  />
                )}
              </div>

              {/* Type */}
              <div>
                <Label className="text-xs">{t('gitCredentials.kind')}</Label>
                <Select
                  value={editForm.kind}
                  onValueChange={v => handleEditKindChange(v as 'ssh' | 'token')}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="token">{t('gitCredentials.kindPat')}</SelectItem>
                    <SelectItem value="ssh">{t('gitCredentials.kindSsh')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Champs PAT */}
              {editForm.kind === 'token' && (
                <>
                  <div>
                    <Label htmlFor="edit-cred-username" className="text-xs">
                      {t('gitCredentials.username')}
                    </Label>
                    <Input
                      id="edit-cred-username"
                      value={editForm.username}
                      onChange={e => setEditForm(f => f ? { ...f, username: e.target.value } : f)}
                      placeholder={t('gitCredentials.usernamePlaceholder')}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="edit-cred-token" className="text-xs">
                      {t('gitCredentials.token')}
                    </Label>
                    <div className="relative mt-1">
                      <Input
                        id="edit-cred-token"
                        type={showToken ? 'text' : 'password'}
                        value={editForm.tokenValue}
                        onFocus={() => {
                          if (!editForm.tokenTouched) {
                            setEditForm(f => f ? { ...f, tokenValue: '' } : f)
                          }
                        }}
                        onChange={e =>
                          setEditForm(f =>
                            f ? { ...f, tokenValue: e.target.value, tokenTouched: true } : f,
                          )
                        }
                        onBlur={() => {
                          setEditForm(f => {
                            if (!f || f.tokenValue !== '') return f
                            return { ...f, tokenValue: SENTINEL, tokenTouched: false }
                          })
                        }}
                        className="pr-9"
                      />
                      <button
                        type="button"
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        onClick={() => setShowToken(v => !v)}
                        tabIndex={-1}
                      >
                        {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>
                </>
              )}

              {/* Champ SSH */}
              {editForm.kind === 'ssh' && (
                <div>
                  <Label htmlFor="edit-cred-key" className="text-xs">
                    {t('gitCredentials.privateKey')}
                  </Label>
                  <Textarea
                    id="edit-cred-key"
                    value={editForm.privateKey}
                    onChange={e =>
                      setEditForm(f =>
                        f
                          ? { ...f, privateKey: e.target.value, keyTouched: e.target.value !== '' }
                          : f,
                      )
                    }
                    placeholder={t('gitCredentials.privateKeyPlaceholder')}
                    className="mt-1 font-mono text-xs"
                    rows={6}
                  />
                  <div className="mt-1.5">
                    <input
                      type="file"
                      accept=".pem,.key"
                      id="edit-cred-key-file"
                      className="hidden"
                      onChange={e => {
                        const file = e.target.files?.[0]
                        if (!file) return
                        const reader = new FileReader()
                        reader.onload = ev =>
                          setEditForm(f =>
                            f
                              ? {
                                  ...f,
                                  privateKey: (ev.target?.result as string) ?? '',
                                  keyTouched: true,
                                }
                              : f,
                          )
                        reader.readAsText(file)
                        e.target.value = ''
                      }}
                    />
                    <Button type="button" variant="outline" size="sm" asChild>
                      <label htmlFor="edit-cred-key-file" className="cursor-pointer">
                        {t('gitCredentials.loadKeyFile')}
                      </label>
                    </Button>
                  </div>
                  {!editForm.keyTouched && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t('gitCredentials.sshKeyUnchangedHint')}
                    </p>
                  )}
                </div>
              )}

              {editError && (
                <p role="alert" className="text-xs text-destructive">{editError}</p>
              )}

              <DialogFooter>
                <Button type="button" variant="ghost" size="sm" onClick={closeEdit}>
                  {t('gitCredentials.cancel')}
                </Button>
                <Button type="submit" size="sm" disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? '…' : t('gitCredentials.save')}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* ── Dialog clé publique ──────────────────────────────────────── */}
      <GitCredentialPublicKeyDialog
        open={!!publicKeyDialog}
        publicKey={publicKeyDialog?.key ?? ''}
        onClose={() => setPublicKeyDialog(null)}
      />
    </div>
  )
}
