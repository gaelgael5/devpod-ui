import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Shield } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useVaultKeys, useAddVaultKey, useDeleteVaultKey, useTestVaultKey } from './api'

const DEFAULT_URL = 'https://harpocrate.yoops.org'

function slugify(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+/, '')
    .replace(/-+$/, '')
    .slice(0, 31)
}

export default function VaultTab() {
  const { t } = useTranslation()
  const { data: keys = [], isLoading } = useVaultKeys()
  const addKey = useAddVaultKey()
  const deleteKey = useDeleteVaultKey()
  const testKey = useTestVaultKey()

  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [url, setUrl] = useState(DEFAULT_URL)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; text: string }>>({})
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const slug = slugify(label)
  const canAdd = slug.length > 0 && apiKey.startsWith('hrpv_') && !addKey.isPending

  function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!canAdd) return
    addKey.mutate(
      { identifier: slug, token: apiKey, url, description },
      {
        onSuccess: () => {
          setLabel('')
          setDescription('')
          setApiKey('')
          setUrl(DEFAULT_URL)
        },
      },
    )
  }

  function handleTest(identifier: string) {
    testKey.mutate(identifier, {
      onSuccess: (r) =>
        setTestResults((prev) => ({
          ...prev,
          [identifier]: { ok: true, text: `wallet: ${r.wallet_id.slice(0, 8)}…` },
        })),
      onError: () =>
        setTestResults((prev) => ({
          ...prev,
          [identifier]: { ok: false, text: t('vault.testFailed') },
        })),
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
      </div>

      {/* ── Formulaire ajout ───────────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <h2 className="font-medium">{t('vault.addKey')}</h2>
        <form onSubmit={handleAdd} className="flex flex-col gap-3">
          <div className="flex gap-4">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="v-label">{t('vault.form.label')}</Label>
              <Input
                id="v-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('vault.form.labelPlaceholder')}
              />
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>{t('vault.form.slug')}</Label>
              <div className="flex h-9 items-center rounded-md border border-input bg-muted px-3 font-mono text-sm text-muted-foreground">
                {slug || (
                  <span className="italic opacity-50">{t('vault.form.slugEmpty')}</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{t('vault.form.slugHint')}</p>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="v-desc">{t('vault.form.description')}</Label>
            <Input
              id="v-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('vault.form.descriptionPlaceholder')}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="v-apikey">{t('vault.form.apiKey')}</Label>
            <Input
              id="v-apikey"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="hrpv_1_…"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="v-url">{t('vault.form.url')}</Label>
            <Input
              id="v-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          {addKey.isError && (
            <Alert variant="destructive">
              <AlertDescription>
                {addKey.error instanceof Error ? addKey.error.message : t('errors.generic')}
              </AlertDescription>
            </Alert>
          )}
          <Button type="submit" disabled={!canAdd} className="self-start">
            {addKey.isPending ? t('vault.form.saving') : t('vault.form.add')}
          </Button>
        </form>
      </section>

      {/* ── Liste des clés enregistrées ────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <h2 className="font-medium">{t('vault.keys')}</h2>
        {isLoading && (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        )}
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
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium">{k.identifier}</span>
                  {testResults[k.identifier] && (
                    <Badge
                      variant={testResults[k.identifier].ok ? 'secondary' : 'destructive'}
                      className="text-xs"
                    >
                      {testResults[k.identifier].text}
                    </Badge>
                  )}
                </div>
                {k.description && (
                  <p className="text-xs text-muted-foreground">{k.description}</p>
                )}
                <p className="font-mono text-xs text-muted-foreground opacity-60">{k.url}</p>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => handleTest(k.identifier)}
                disabled={testKey.isPending}
              >
                {t('vault.test')}
              </Button>
              {confirmDelete === k.identifier ? (
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() =>
                      deleteKey.mutate(k.identifier, {
                        onSuccess: () => setConfirmDelete(null),
                      })
                    }
                    disabled={deleteKey.isPending}
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
    </div>
  )
}
