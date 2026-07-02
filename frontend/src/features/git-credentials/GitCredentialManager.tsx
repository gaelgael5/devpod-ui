import { useState, useEffect, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, KeyRound, Pencil, PlugZap, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
  useTestGitCredential,
  type GitCredentialSummary,
  type UpdateCredentialPayload,
} from './useGitCredentials'
import { useCertificates } from '@/features/certificates/api'
import { useSecrets } from '@/features/secrets/api'

const KNOWN_HOSTS = [
  { value: 'github.com', labelKey: 'gitCredentials.hosts.github' },
  { value: 'gitlab.com', labelKey: 'gitCredentials.hosts.gitlab' },
  { value: 'bitbucket.org', labelKey: 'gitCredentials.hosts.bitbucket' },
  { value: 'dev.azure.com', labelKey: 'gitCredentials.hosts.azure' },
  { value: 'codeberg.org', labelKey: 'gitCredentials.hosts.codeberg' },
  { value: '__other__', labelKey: 'gitCredentials.hosts.other' },
] as const

type KnownHostValue = (typeof KNOWN_HOSTS)[number]['value']

const HOST_TO_SECRET_TYPE: Record<string, string> = {
  'github.com': 'PAT_GITHUB',
  'gitlab.com': 'PAT_GITLAB',
  'dev.azure.com': 'PAT_AZURE',
  'bitbucket.org': 'API_KEY',
}

function hostSecretType(host: string): string {
  return HOST_TO_SECRET_TYPE[host] ?? 'API_KEY'
}

const EMPTY_FORM = {
  name: '',
  hostSelect: 'github.com' as KnownHostValue,
  hostCustom: '',
  kind: 'token' as 'ssh' | 'token',
  username: '',
  cert_slug: '',
  secret_slug: '',
}

type EditFormState = {
  name: string
  hostSelect: KnownHostValue
  hostCustom: string
  kind: 'ssh' | 'token'
  username: string
  cert_slug: string
  secret_slug: string
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
    cert_slug: '',
    secret_slug: '',
  }
}

export default function GitCredentialManager() {
  const { t } = useTranslation()
  const { data: credentials, isError } = useGitCredentials()
  const addMutation = useAddGitCredential()
  const deleteMutation = useDeleteGitCredential()
  const updateMutation = useUpdateGitCredential()
  const testMutation = useTestGitCredential()

  function handleTest(name: string) {
    testMutation.mutate(name, {
      onSuccess: (res) => {
        if (res.ok) {
          toast.success(t('gitCredentials.testSuccess'), { description: res.message || undefined })
        } else {
          toast.error(t('gitCredentials.testFailure'), { description: res.message || undefined })
        }
      },
      onError: (err: unknown) =>
        toast.error(err instanceof Error ? err.message : t('gitCredentials.testFailure')),
    })
  }

  function mapApiError(err: unknown, fallbackKey: string): string {
    const msg = err instanceof Error ? err.message : ''
    if (msg.includes('vault_locked')) return t('gitCredentials.errors.vaultLocked')
    if (msg.includes('cert_not_found')) return t('gitCredentials.errors.certNotFound')
    if (msg.includes('secret_not_found')) return t('gitCredentials.errors.secretNotFound')
    return msg || t(fallbackKey)
  }

  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [toDelete, setToDelete] = useState<GitCredentialSummary | null>(null)
  const [toEdit, setToEdit] = useState<GitCredentialSummary | null>(null)
  const [editForm, setEditForm] = useState<EditFormState | null>(null)
  const [editError, setEditError] = useState('')

  const effectiveHost =
    form.hostSelect === '__other__' ? form.hostCustom.trim() : form.hostSelect

  const { data: certificates = [] } = useCertificates()
  const { data: addSecrets = [] } = useSecrets(
    form.kind === 'token' ? hostSecretType(effectiveHost) : undefined,
  )

  const editEffectiveHost = editForm
    ? editForm.hostSelect === '__other__' ? editForm.hostCustom.trim() : editForm.hostSelect
    : ''
  const { data: editSecrets = [] } = useSecrets(
    editForm?.kind === 'token' ? hostSecretType(editEffectiveHost) : undefined,
  )

  const ownCertificates = certificates.filter(c => c.is_own)
  const ownAddSecrets = addSecrets.filter(s => s.is_own)
  const ownEditSecrets = editSecrets.filter(s => s.is_own)

  const credentialList: GitCredentialSummary[] = credentials ?? []

  // Réinitialiser les slugs quand le kind change
  useEffect(() => {
    setForm(f => ({ ...f, cert_slug: '', secret_slug: '' }))
  }, [form.kind])

  function resetForm() {
    setForm(EMPTY_FORM)
    setFormError('')
    setShowForm(false)
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError('')

    if (form.kind === 'ssh' && !form.cert_slug) {
      setFormError(t('gitCredentials.errors.selectCert'))
      return
    }
    if (form.kind === 'token' && !form.secret_slug) {
      setFormError(t('gitCredentials.errors.selectSecret'))
      return
    }

    addMutation.mutate(
      {
        name: form.name.trim(),
        host: effectiveHost,
        kind: form.kind,
        username: form.username.trim() || undefined,
        cert_slug: form.kind === 'ssh' ? form.cert_slug : undefined,
        secret_slug: form.kind === 'token' ? form.secret_slug : undefined,
      },
      {
        onSuccess: () => resetForm(),
        onError: (err: unknown) => setFormError(mapApiError(err, 'gitCredentials.errors.add')),
      },
    )
  }

  function handleDelete() {
    if (!toDelete) return
    deleteMutation.mutate(toDelete.name, {
      onSuccess: () => setToDelete(null),
    })
  }

  function openEdit(c: GitCredentialSummary) {
    setToEdit(c)
    setEditForm(initEditForm(c))
    setEditError('')
  }

  function closeEdit() {
    setToEdit(null)
    setEditForm(null)
    setEditError('')
  }

  function handleEditSubmit(e: FormEvent) {
    e.preventDefault()
    if (!toEdit || !editForm) return
    setEditError('')

    const editEffHost =
      editForm.hostSelect === '__other__' ? editForm.hostCustom.trim() : editForm.hostSelect

    const payload: UpdateCredentialPayload = {
      host: editEffHost,
      kind: editForm.kind,
      username: editForm.username.trim(),
    }
    if (editForm.name.trim() !== toEdit.name) payload.new_name = editForm.name.trim()
    if (editForm.kind === 'ssh' && editForm.cert_slug) payload.cert_slug = editForm.cert_slug
    if (editForm.kind === 'token' && editForm.secret_slug) payload.secret_slug = editForm.secret_slug

    updateMutation.mutate(
      { name: toEdit.name, payload },
      {
        onSuccess: () => closeEdit(),
        onError: (err: unknown) => setEditError(mapApiError(err, 'gitCredentials.errors.update')),
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
              onValueChange={v =>
                setForm(f => ({
                  ...f,
                  hostSelect: v as KnownHostValue,
                  cert_slug: '',
                  secret_slug: '',
                }))
              }
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
              onValueChange={v =>
                setForm(f => ({
                  ...f,
                  kind: v as 'ssh' | 'token',
                  cert_slug: '',
                  secret_slug: '',
                }))
              }
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

          {/* Sélection du certificat SSH */}
          {form.kind === 'ssh' && (
            <div>
              <Label className="text-xs">{t('gitCredentials.certificate')}</Label>
              <Select
                value={form.cert_slug}
                onValueChange={v => setForm(f => ({ ...f, cert_slug: v }))}
              >
                <SelectTrigger className="mt-1">
                  <SelectValue placeholder={t('gitCredentials.selectCertificate')} />
                </SelectTrigger>
                <SelectContent>
                  {ownCertificates.map(c => (
                    <SelectItem key={c.slug} value={c.slug}>
                      {c.label}
                      <span className="ml-1 text-xs text-muted-foreground">({c.cert_type})</span>
                    </SelectItem>
                  ))}
                  {ownCertificates.length === 0 && (
                    <div className="p-2 text-xs text-muted-foreground">
                      {t('gitCredentials.noCertificates')}
                    </div>
                  )}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Sélection du secret PAT */}
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
                <Label className="text-xs">{t('gitCredentials.token')}</Label>
                <Select
                  value={form.secret_slug}
                  onValueChange={v => setForm(f => ({ ...f, secret_slug: v }))}
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue placeholder={t('gitCredentials.selectSecret')} />
                  </SelectTrigger>
                  <SelectContent>
                    {ownAddSecrets.map(s => (
                      <SelectItem key={s.slug} value={s.slug}>
                        {s.label}
                      </SelectItem>
                    ))}
                    {ownAddSecrets.length === 0 && (
                      <div className="p-2 text-xs text-muted-foreground">
                        {t('gitCredentials.noSecretsForHost')}
                      </div>
                    )}
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {formError && (
            <p role="alert" className="text-xs text-destructive">{formError}</p>
          )}

          <div className="flex gap-2 justify-end">
            <Button type="button" variant="ghost" size="sm" onClick={resetForm}>
              {t('gitCredentials.cancel')}
            </Button>
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
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={() => handleTest(c.name)}
                disabled={testMutation.isPending && testMutation.variables === c.name}
                aria-label={t('gitCredentials.testConnection')}
              >
                {testMutation.isPending && testMutation.variables === c.name ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <PlugZap className="h-4 w-4" />
                )}
              </Button>
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
                  onValueChange={v =>
                    setEditForm(f =>
                      f
                        ? { ...f, hostSelect: v as KnownHostValue, cert_slug: '', secret_slug: '' }
                        : f,
                    )
                  }
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
                  onValueChange={v =>
                    setEditForm(f =>
                      f
                        ? { ...f, kind: v as 'ssh' | 'token', cert_slug: '', secret_slug: '' }
                        : f,
                    )
                  }
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

              {/* Certificat SSH */}
              {editForm.kind === 'ssh' && (
                <div>
                  <Label className="text-xs">
                    {t('gitCredentials.certificate')}
                    <span className="ml-1 text-xs text-muted-foreground">
                      ({t('gitCredentials.leaveEmptyToKeep')})
                    </span>
                  </Label>
                  <Select
                    value={editForm.cert_slug}
                    onValueChange={v => setEditForm(f => f ? { ...f, cert_slug: v } : f)}
                  >
                    <SelectTrigger className="mt-1">
                      <SelectValue placeholder={t('gitCredentials.selectCertificate')} />
                    </SelectTrigger>
                    <SelectContent>
                      {ownCertificates.map(c => (
                        <SelectItem key={c.slug} value={c.slug}>
                          {c.label}
                          <span className="ml-1 text-xs text-muted-foreground">({c.cert_type})</span>
                        </SelectItem>
                      ))}
                      {ownCertificates.length === 0 && (
                        <div className="p-2 text-xs text-muted-foreground">
                          {t('gitCredentials.noCertificates')}
                        </div>
                      )}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {/* Secret PAT */}
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
                    <Label className="text-xs">
                      {t('gitCredentials.token')}
                      <span className="ml-1 text-xs text-muted-foreground">
                        ({t('gitCredentials.leaveEmptyToKeep')})
                      </span>
                    </Label>
                    <Select
                      value={editForm.secret_slug}
                      onValueChange={v => setEditForm(f => f ? { ...f, secret_slug: v } : f)}
                    >
                      <SelectTrigger className="mt-1">
                        <SelectValue placeholder={t('gitCredentials.selectSecret')} />
                      </SelectTrigger>
                      <SelectContent>
                        {ownEditSecrets.map(s => (
                          <SelectItem key={s.slug} value={s.slug}>
                            {s.label}
                          </SelectItem>
                        ))}
                        {ownEditSecrets.length === 0 && (
                          <div className="p-2 text-xs text-muted-foreground">
                            {t('gitCredentials.noSecretsForHost')}
                          </div>
                        )}
                      </SelectContent>
                    </Select>
                  </div>
                </>
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
    </div>
  )
}
