import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, Plus, Eye, EyeOff, Copy, Check, Pencil } from 'lucide-react'
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
import { Textarea } from '@/components/ui/textarea'
import {
  useCertificates,
  useGenerateCertificate,
  useRegisterCertificate,
  useDeleteCertificate,
  useRevealPrivateKey,
  useUpdateCertificate,
  type Certificate,
  type CertType,
  type EditCertBody,
  type GenerateBody,
} from './api'
import { useVaultKeys } from '@/features/vault/api'

const CERT_TYPES: { value: CertType; label: string }[] = [
  { value: 'ssh-ed25519', label: 'SSH Ed25519 (recommandé)' },
  { value: 'ssh-rsa-2048', label: 'SSH RSA 2048' },
  { value: 'ssh-rsa-4096', label: 'SSH RSA 4096' },
  { value: 'ssh-ecdsa-p256', label: 'SSH ECDSA P-256' },
  { value: 'tls-rsa-2048', label: 'TLS RSA 2048' },
  { value: 'tls-rsa-4096', label: 'TLS RSA 4096' },
  { value: 'tls-ec-p256', label: 'TLS EC P-256' },
  { value: 'tls-ec-p384', label: 'TLS EC P-384' },
]

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
      {copied ? t('certificates.copied') : t('certificates.copy')}
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
  const generate = useGenerateCertificate()
  const register = useRegisterCertificate()

  const [mode, setMode] = useState<'generate' | 'paste'>('generate')
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [certType, setCertType] = useState<CertType>('ssh-ed25519')
  const [storage, setStorage] = useState<'local' | 'harpocrate'>('local')
  const [vaultId, setVaultId] = useState('')
  const [pubKey, setPubKey] = useState('')
  const [privKey, setPrivKey] = useState('')

  const slug = slugify(label)
  const isPending = generate.isPending || register.isPending

  function reset() {
    setLabel('')
    setDescription('')
    setCertType('ssh-ed25519')
    setStorage('local')
    setVaultId('')
    setPubKey('')
    setPrivKey('')
    generate.reset()
    register.reset()
  }

  function close() {
    reset()
    onClose()
  }

  function handleGenerate() {
    if (!slug) return
    const body: GenerateBody = {
      slug,
      label,
      description,
      cert_type: certType,
      storage_type: storage,
      vault_identifier: storage === 'harpocrate' ? vaultId : null,
    }
    generate.mutate(body, { onSuccess: close })
  }

  function handlePaste() {
    if (!slug || !pubKey || !privKey) return
    register.mutate(
      {
        slug,
        label,
        description,
        cert_type: certType,
        public_key: pubKey,
        private_key_pem: privKey,
        storage_type: storage,
        vault_identifier: storage === 'harpocrate' ? vaultId : null,
      },
      { onSuccess: close },
    )
  }

  const error = generate.error ?? register.error
  const canSubmit =
    !!slug &&
    !isPending &&
    (mode === 'generate' || (!!pubKey && !!privKey)) &&
    (storage !== 'harpocrate' || !!vaultId)

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {mode === 'generate'
              ? t('certificates.dialogGenerateTitle')
              : t('certificates.dialogRegisterTitle')}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          {/* Mode switch */}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={mode === 'generate' ? 'default' : 'outline'}
              onClick={() => setMode('generate')}
            >
              {t('certificates.form.generateMode')}
            </Button>
            <Button
              size="sm"
              variant={mode === 'paste' ? 'default' : 'outline'}
              onClick={() => setMode('paste')}
            >
              {t('certificates.form.pasteMode')}
            </Button>
          </div>

          {/* Label + slug */}
          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('certificates.form.label')}</Label>
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('certificates.form.labelPlaceholder')}
              />
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('certificates.form.slug')}</Label>
              <div className="flex h-9 items-center rounded-md border bg-muted px-3 font-mono text-sm text-muted-foreground">
                {slug || (
                  <span className="italic opacity-50">{t('certificates.form.slugEmpty')}</span>
                )}
              </div>
            </div>
          </div>

          {/* Description */}
          <div className="flex flex-col gap-1.5">
            <Label>{t('certificates.form.description')}</Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('certificates.form.descriptionPlaceholder')}
            />
          </div>

          {/* Type + storage */}
          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('certificates.form.certType')}</Label>
              <Select value={certType} onValueChange={(v) => setCertType(v as CertType)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CERT_TYPES.map((ct) => (
                    <SelectItem key={ct.value} value={ct.value}>{ct.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('certificates.form.storageType')}</Label>
              <Select value={storage} onValueChange={(v) => setStorage(v as 'local' | 'harpocrate')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">{t('certificates.form.storageLocal')}</SelectItem>
                  <SelectItem value="harpocrate" disabled={vaultKeys.length === 0}>
                    {t('certificates.form.storageHarpocrate')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Vault wallet selector */}
          {storage === 'harpocrate' && (
            <div className="flex flex-col gap-1.5">
              <Label>{t('certificates.form.vaultWallet')}</Label>
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

          {/* Paste mode fields */}
          {mode === 'paste' && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label>{t('certificates.form.publicKey')}</Label>
                <Textarea
                  rows={2}
                  value={pubKey}
                  onChange={(e) => setPubKey(e.target.value)}
                  className="font-mono text-xs"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>{t('certificates.form.privateKey')}</Label>
                <Textarea
                  rows={4}
                  value={privKey}
                  onChange={(e) => setPrivKey(e.target.value)}
                  className="font-mono text-xs"
                />
              </div>
            </>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertDescription>
                {error instanceof Error ? error.message : t('errors.generic')}
              </AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button
            onClick={mode === 'generate' ? handleGenerate : handlePaste}
            disabled={!canSubmit}
          >
            {isPending
              ? (mode === 'generate'
                  ? t('certificates.form.generating')
                  : t('certificates.form.saving'))
              : (mode === 'generate'
                  ? t('certificates.generateKey')
                  : t('certificates.form.save'))}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface EditDialogProps {
  cert: Certificate | null
  onClose: () => void
}

function EditDialog({ cert, onClose }: EditDialogProps) {
  const { t } = useTranslation()
  const update = useUpdateCertificate()
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [newPubKey, setNewPubKey] = useState('')
  const [newPrivKey, setNewPrivKey] = useState('')

  useEffect(() => {
    if (cert) {
      setLabel(cert.label)
      setDescription(cert.description)
      setNewPubKey('')
      setNewPrivKey('')
      update.reset()
    }
  }, [cert?.slug]) // eslint-disable-line react-hooks/exhaustive-deps

  function handleSave() {
    if (!cert) return
    const body: EditCertBody & { slug: string } = {
      slug: cert.slug,
      label,
      description,
      new_public_key: newPubKey.trim() || null,
      new_private_key_pem: newPrivKey.trim() || null,
    }
    update.mutate(body, { onSuccess: onClose })
  }

  const canSave = !!label.trim() && !update.isPending

  return (
    <Dialog open={!!cert} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('certificates.dialogEditTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>{t('certificates.form.label')}</Label>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('certificates.form.description')}</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('certificates.form.publicKey')} <span className="text-muted-foreground text-xs">({t('common.optional', 'optionnel')})</span></Label>
            <Textarea rows={2} value={newPubKey} onChange={(e) => setNewPubKey(e.target.value)} className="font-mono text-xs" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('certificates.form.privateKey')} <span className="text-muted-foreground text-xs">({t('common.optional', 'optionnel')})</span></Label>
            <Textarea rows={4} value={newPrivKey} onChange={(e) => setNewPrivKey(e.target.value)} className="font-mono text-xs" />
          </div>
          {update.error && (
            <Alert variant="destructive">
              <AlertDescription>
                {update.error instanceof Error ? update.error.message : t('errors.generic')}
              </AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSave} disabled={!canSave}>
            {update.isPending ? t('certificates.form.saving') : t('certificates.form.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CertRow({ cert }: { cert: Certificate }) {
  const { t } = useTranslation()
  const deleteC = useDeleteCertificate()
  const reveal = useRevealPrivateKey()
  const [showPrivate, setShowPrivate] = useState(false)
  const [privateKey, setPrivateKey] = useState<string | null>(null)
  const [confirmDel, setConfirmDel] = useState(false)
  const [editOpen, setEditOpen] = useState(false)

  function toggleReveal() {
    if (showPrivate) {
      // Masquer : effacer la clé de la mémoire
      setShowPrivate(false)
      setPrivateKey(null)
      return
    }
    // Révéler
    if (privateKey) {
      setShowPrivate(true)
      return
    }
    reveal.mutate(cert.slug, {
      onSuccess: (r) => {
        setPrivateKey(r.private_key_pem)
        setShowPrivate(true)
      },
    })
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card p-3">
      {/* Header row */}
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="flex-1 font-medium">{cert.label}</span>
        <Badge variant="outline" className="font-mono text-xs">{cert.cert_type}</Badge>
        {cert.is_public && (
          <Badge variant="secondary">{t('certificates.publicBadge')}</Badge>
        )}
      </div>

      {cert.description && (
        <p className="text-xs text-muted-foreground">{cert.description}</p>
      )}

      {/* Public key */}
      <div className="flex items-center gap-1 rounded bg-muted/50 p-2 font-mono text-xs break-all">
        <span className="flex-1 select-all">{cert.public_key}</span>
        <CopyButton text={cert.public_key} />
      </div>

      {/* Private key (revealed) */}
      {showPrivate && privateKey && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">{t('certificates.privateKeyLabel')}</span>
          <div className="flex items-start gap-1 rounded bg-muted/50 p-2 font-mono text-xs break-all">
            <pre className="flex-1 whitespace-pre-wrap select-all">{privateKey}</pre>
            <CopyButton text={privateKey} />
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        {cert.storage_type === 'local' && cert.is_own && (
          <Button
            size="sm"
            variant="outline"
            onClick={toggleReveal}
            disabled={reveal.isPending}
          >
            {showPrivate
              ? <EyeOff className="mr-1 h-3.5 w-3.5" />
              : <Eye className="mr-1 h-3.5 w-3.5" />}
            {showPrivate
              ? t('certificates.hidePrivate')
              : t('certificates.revealPrivate')}
          </Button>
        )}

        {cert.is_own && (
          <Button size="sm" variant="outline" onClick={() => setEditOpen(true)}>
            <Pencil className="mr-1 h-3.5 w-3.5" />
            {t('workspaces.actions.edit')}
          </Button>
        )}

        {cert.is_own && (
          confirmDel ? (
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="destructive"
                disabled={deleteC.isPending}
                onClick={() => deleteC.mutate(cert.slug, { onSuccess: () => setConfirmDel(false) })}
              >
                {t('certificates.confirmDelete')}
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
      <EditDialog cert={editOpen ? cert : null} onClose={() => setEditOpen(false)} />
    </div>
  )
}

export default function CertificatesTab() {
  const { t } = useTranslation()
  const { data: certs = [], isLoading } = useCertificates()
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="flex flex-col gap-6">
      {/* Info block */}
      <div className="rounded-lg border bg-muted/40 p-5">
        <div className="mb-2 flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{t('certificates.title')}</span>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">{t('certificates.info')}</p>
      </div>

      {/* List header */}
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('certificates.tabLabel')}</h2>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />
          {t('certificates.addKey')}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && certs.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('certificates.noKeys')}</p>
      )}

      <div className="flex flex-col gap-3">
        {certs.map((c) => (
          <CertRow key={`${c.owner_login}/${c.slug}`} cert={c} />
        ))}
      </div>

      <AddDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}
