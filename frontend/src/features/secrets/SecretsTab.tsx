import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, Plus, Eye, EyeOff, Copy, Check, Pencil, ExternalLink } from 'lucide-react'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  useSecrets,
  useRegisterSecret,
  useEditSecret,
  useRevealSecret,
  useDeleteSecret,
  type Secret,
} from './api'
import { useVaultKeys } from '@/features/vault/api'

const PAT_PROVIDERS = [
  {
    key: 'github',
    docUrl:
      'https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens',
  },
  {
    key: 'gitlab',
    docUrl: 'https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html',
  },
  {
    key: 'bitbucket',
    docUrl: 'https://support.atlassian.com/bitbucket-cloud/docs/create-an-app-password/',
  },
  {
    key: 'azure',
    docUrl:
      'https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate',
  },
] as const

function slugify(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+/, '')
    .replace(/-+$/, '')
    .slice(0, 63)
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  function copy() {
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Button size="sm" variant="ghost" onClick={copy}>
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t('secrets.copied') : t('secrets.copy')}
    </Button>
  )
}

interface AddDialogProps {
  open: boolean
  onClose: () => void
}

function AddDialog({ open, onClose }: AddDialogProps) {
  const { t } = useTranslation()
  const { data: vaultKeys = [] } = useVaultKeys()
  const register = useRegisterSecret()

  const SECRET_TYPES: { value: string; label: string }[] = [
    { value: 'PAT_GITHUB', label: t('secrets.types.PAT_GITHUB') },
    { value: 'PAT_GITLAB', label: t('secrets.types.PAT_GITLAB') },
    { value: 'PAT_AZURE', label: t('secrets.types.PAT_AZURE') },
    { value: 'API_KEY', label: t('secrets.types.API_KEY') },
  ]

  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [secretType, setSecretType] = useState('PAT_GITHUB')
  const [secretValue, setSecretValue] = useState('')
  const [storage, setStorage] = useState<'local' | 'harpocrate'>('local')
  const [vaultId, setVaultId] = useState('')

  const slug = slugify(label)
  const isPending = register.isPending

  function reset() {
    setLabel('')
    setDescription('')
    setSecretType('PAT_GITHUB')
    setSecretValue('')
    setStorage('local')
    setVaultId('')
    register.reset()
  }

  function close() {
    reset()
    onClose()
  }

  function handleSubmit() {
    if (!slug || !secretValue) return
    register.mutate(
      {
        slug,
        label,
        description,
        secret_type: secretType,
        secret_value: secretValue,
        storage_type: storage,
        vault_identifier: storage === 'harpocrate' ? vaultId : null,
      },
      { onSuccess: close },
    )
  }

  const canSubmit =
    !!slug &&
    !!secretValue &&
    !isPending &&
    (storage !== 'harpocrate' || !!vaultId)

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('secrets.dialogAddTitle')}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {/* Label + slug */}
          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('secrets.form.label')}</Label>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('secrets.form.labelPlaceholder')}
              />
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('secrets.form.slug')}</Label>
              <div className="flex h-9 items-center rounded-md border bg-muted px-3 font-mono text-sm text-muted-foreground">
                {slug || (
                  <span className="italic opacity-50">{t('secrets.form.slugEmpty')}</span>
                )}
              </div>
            </div>
          </div>

          {/* Description */}
          <div className="flex flex-col gap-1.5">
            <Label>{t('secrets.form.description')}</Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('secrets.form.descriptionPlaceholder')}
            />
          </div>

          {/* Type + storage */}
          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('secrets.form.secretType')}</Label>
              <Select value={secretType} onValueChange={setSecretType}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SECRET_TYPES.map((st) => (
                    <SelectItem key={st.value} value={st.value}>{st.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('secrets.form.storageType')}</Label>
              <Select value={storage} onValueChange={(v) => setStorage(v as 'local' | 'harpocrate')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">{t('secrets.form.storageLocal')}</SelectItem>
                  <SelectItem value="harpocrate" disabled={vaultKeys.length === 0}>
                    {t('secrets.form.storageHarpocrate')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Vault wallet selector */}
          {storage === 'harpocrate' && (
            <div className="flex flex-col gap-1.5">
              <Label>{t('secrets.form.vaultWallet')}</Label>
              <Select value={vaultId} onValueChange={setVaultId}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {vaultKeys.map((k) => (
                    <SelectItem key={k.identifier} value={k.identifier}>
                      {k.identifier}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Secret value */}
          <div className="flex flex-col gap-1.5">
            <Label>{t('secrets.form.secretValue')}</Label>
            <Input
              type="password"
              value={secretValue}
              onChange={(e) => setSecretValue(e.target.value)}
              placeholder={t('secrets.form.secretValuePlaceholder')}
            />
          </div>

          {register.error && (
            <Alert variant="destructive">
              <AlertDescription>
                {register.error instanceof Error
                  ? register.error.message
                  : t('errors.generic')}
              </AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {isPending ? t('secrets.form.saving') : t('secrets.form.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface EditDialogProps {
  secret: Secret | null
  onClose: () => void
}

function EditDialog({ secret, onClose }: EditDialogProps) {
  const { t } = useTranslation()
  const edit = useEditSecret()

  const [label, setLabel] = useState(secret?.label ?? '')
  const [description, setDescription] = useState(secret?.description ?? '')
  const [newValue, setNewValue] = useState('')

  // Sync fields when the target secret changes (new edit opens)
  useEffect(() => {
    if (secret) {
      setLabel(secret.label)
      setDescription(secret.description)
      setNewValue('')
      edit.reset()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [secret?.slug])

  function close() {
    setLabel('')
    setDescription('')
    setNewValue('')
    edit.reset()
    onClose()
  }

  function handleSubmit() {
    if (!secret) return
    edit.mutate(
      {
        slug: secret.slug,
        label,
        description,
        new_value: newValue.trim() !== '' ? newValue : null,
      },
      { onSuccess: close },
    )
  }

  const canSubmit = !!label.trim() && !edit.isPending

  return (
    <Dialog open={secret !== null} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('secrets.dialogEditTitle')}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {/* Label */}
          <div className="flex flex-col gap-1.5">
            <Label>{t('secrets.form.label')}</Label>
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('secrets.form.labelPlaceholder')}
            />
          </div>

          {/* Description */}
          <div className="flex flex-col gap-1.5">
            <Label>{t('secrets.form.description')}</Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('secrets.form.descriptionPlaceholder')}
            />
          </div>

          {/* New value (optional) */}
          <div className="flex flex-col gap-1.5">
            <Label>{t('secrets.form.newValue')}</Label>
            <Input
              type="password"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              placeholder={t('secrets.form.secretValuePlaceholder')}
            />
          </div>

          {edit.error && (
            <Alert variant="destructive">
              <AlertDescription>
                {edit.error instanceof Error
                  ? edit.error.message
                  : t('errors.generic')}
              </AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {edit.isPending ? t('secrets.form.saving') : t('secrets.form.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SecretRow({ secret }: { secret: Secret }) {
  const { t } = useTranslation()
  const deleteS = useDeleteSecret()
  const reveal = useRevealSecret()
  const [showValue, setShowValue] = useState(false)
  const [revealedValue, setRevealedValue] = useState<string | null>(null)
  const [confirmDel, setConfirmDel] = useState(false)
  const [editTarget, setEditTarget] = useState<Secret | null>(null)

  function toggleReveal() {
    if (showValue) {
      // Masquer : effacer la valeur de la mémoire
      setShowValue(false)
      setRevealedValue(null)
      return
    }
    if (revealedValue) {
      setShowValue(true)
      return
    }
    reveal.mutate(secret.slug, {
      onSuccess: (r) => {
        setRevealedValue(r.secret_value)
        setShowValue(true)
      },
    })
  }

  return (
    <>
      <div className="flex flex-col gap-2 rounded-lg border bg-card p-3">
        {/* Header row */}
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="flex-1 font-medium">{secret.label}</span>
          <Badge variant="outline" className="font-mono text-xs">{secret.secret_type}</Badge>
          {secret.is_public && (
            <Badge variant="secondary">{t('secrets.publicBadge')}</Badge>
          )}
        </div>

        {secret.description && (
          <p className="text-xs text-muted-foreground">{secret.description}</p>
        )}

        {/* Revealed value */}
        {showValue && revealedValue && (
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">{t('secrets.valueLabel')}</span>
            <div className="flex items-center gap-1 rounded bg-muted/50 p-2">
              <code className="flex-1 break-all text-xs select-all">{revealedValue}</code>
              <CopyButton text={revealedValue} />
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2">
          {secret.is_own && (
            <Button
              size="sm"
              variant="outline"
              onClick={toggleReveal}
              disabled={reveal.isPending}
            >
              {showValue
                ? <EyeOff className="mr-1 h-3.5 w-3.5" />
                : <Eye className="mr-1 h-3.5 w-3.5" />}
              {showValue ? t('secrets.hideValue') : t('secrets.revealValue')}
            </Button>
          )}

          {secret.is_own && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setEditTarget(secret)}
            >
              <Pencil className="mr-1 h-3.5 w-3.5" />
              {t('workspaces.actions.edit')}
            </Button>
          )}

          {secret.is_own && (
            confirmDel ? (
              <div className="flex gap-1">
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={deleteS.isPending}
                  onClick={() =>
                    deleteS.mutate(secret.slug, { onSuccess: () => setConfirmDel(false) })
                  }
                >
                  {t('secrets.confirmDelete')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmDel(false)}>
                  {t('common.cancel')}
                </Button>
              </div>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive hover:text-destructive"
                onClick={() => setConfirmDel(true)}
              >
                {t('workspaces.actions.delete')}
              </Button>
            )
          )}
        </div>
      </div>

      <EditDialog secret={editTarget} onClose={() => setEditTarget(null)} />
    </>
  )
}

export default function SecretsTab() {
  const { t } = useTranslation()
  const { data: secrets = [], isLoading } = useSecrets()
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="flex flex-col gap-6">
      {/* Info block */}
      <div className="rounded-lg border bg-muted/40 p-5">
        <div className="mb-2 flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{t('secrets.title')}</span>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">{t('secrets.info')}</p>
      </div>

      {/* How to get a PAT */}
      <details className="rounded-lg border bg-card">
        <summary className="cursor-pointer px-5 py-3 text-sm font-medium">
          {t('secrets.patHelp.title')}
        </summary>
        <div className="flex flex-col gap-3 border-t px-5 py-4 text-sm text-muted-foreground">
          <p className="leading-relaxed">{t('secrets.patHelp.intro')}</p>
          <ul className="flex flex-col gap-2">
            {PAT_PROVIDERS.map((p) => (
              <li key={p.key} className="leading-relaxed">
                {t(`secrets.patHelp.${p.key}`)}{' '}
                <a
                  href={p.docUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 whitespace-nowrap text-primary underline underline-offset-2"
                >
                  {t('secrets.patHelp.docLink')}
                  <ExternalLink className="h-3 w-3" />
                </a>
              </li>
            ))}
          </ul>
        </div>
      </details>

      {/* List header */}
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('secrets.tabLabel')}</h2>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />
          {t('secrets.addSecret')}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && secrets.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('secrets.noSecrets')}</p>
      )}

      <div className="flex flex-col gap-3">
        {secrets.map((s) => (
          <SecretRow key={`${s.owner_login}/${s.slug}`} secret={s} />
        ))}
      </div>

      <AddDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}
