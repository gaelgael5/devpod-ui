// Briques partagées de l'éditeur de règle (extraites de l'ancienne popup) :
// palette de variables, arbre des events, sélecteur de secret, éditeur d'en-têtes.

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SELECT_CLS, slugify, type HeaderDraft } from './editor-utils'
import { useCreateSystemSecret, useSystemSecrets } from './useAutomations'

// ─── Palette de variables copiables (contextuelle events + réponses nommées) ───

export function VariablesPalette({
  variables,
  copied,
  onCopy,
}: {
  variables: string[]
  copied: string | null
  onCopy: (v: string) => void
}) {
  const { t } = useTranslation()
  if (variables.length === 0) return null
  return (
    <div className="flex flex-wrap justify-end gap-1">
      <span className="mr-1 text-xs text-muted-foreground">
        {t('automations.form.variables')} :
      </span>
      {variables.map((v) => (
        <button
          key={v}
          type="button"
          onClick={() => onCopy(v)}
          className={`rounded px-1.5 py-0.5 font-mono text-xs transition-colors ${
            copied === v ? 'bg-primary/20 text-primary' : 'bg-muted hover:bg-muted-foreground/20'
          }`}
        >
          {copied === v ? '✓' : `{${v}}`}
        </button>
      ))}
    </div>
  )
}

// ─── Arbre des events (groupés par domaine `user.*`, `workspace.*`, …) ─────────

export function EventsTree({
  codes,
  selected,
  onToggle,
}: {
  codes: string[]
  selected: string[]
  onToggle: (code: string) => void
}) {
  const groups = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const code of codes) {
      const domain = code.includes('.') ? code.split('.')[0] : 'autre'
      m.set(domain, [...(m.get(domain) ?? []), code])
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [codes])

  return (
    <div className="max-h-64 space-y-1 overflow-y-auto rounded-md border p-2">
      {groups.map(([domain, members]) => (
        // Replié par défaut ; ouvert seulement si le domaine porte une sélection
        // (ne jamais masquer les events déjà cochés).
        <details key={domain} open={members.some((c) => selected.includes(c))} className="group">
          <summary className="cursor-pointer select-none text-xs font-semibold text-muted-foreground">
            {domain}
            {members.filter((c) => selected.includes(c)).length > 0 && (
              <span className="ml-1 text-primary">
                ({members.filter((c) => selected.includes(c)).length})
              </span>
            )}
          </summary>
          <div className="ml-3 mt-1 space-y-1 border-l pl-3">
            {members.map((code) => (
              <label key={code} className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(code)}
                  onChange={() => onToggle(code)}
                />
                <span className="font-mono text-xs">{code}</span>
              </label>
            ))}
          </div>
        </details>
      ))}
    </div>
  )
}

// ─── Sélecteur de secret système (+ création inline) ───────────────────────────

export function SecretPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (v: string) => void
}) {
  const { t } = useTranslation()
  const secrets = useSystemSecrets()
  const createSecret = useCreateSystemSecret()
  const [creating, setCreating] = useState(false)
  const [slug, setSlug] = useState('')
  const [labelTxt, setLabelTxt] = useState('')
  const [secretValue, setSecretValue] = useState('')

  const known = secrets.data ?? []
  const orphan = value && !known.some((s) => `\${system://${s.slug}}` === value)

  function doCreate() {
    const s = slugify(slug || labelTxt)
    if (!s || !secretValue) return
    createSecret.mutate(
      { slug: s, label: labelTxt || s, value: secretValue },
      {
        onSuccess: (r) => {
          onChange(r.ref)
          setCreating(false)
          setSlug('')
          setLabelTxt('')
          setSecretValue('')
          toast.success(t('automations.form.secretCreated'))
        },
      },
    )
  }

  return (
    <div className="min-w-0 flex-1 space-y-1">
      <div className="flex items-center gap-1">
        <select value={value} onChange={(e) => onChange(e.target.value)} className={SELECT_CLS}>
          <option value="">{t('automations.form.chooseSecret')}</option>
          {known.map((s) => (
            <option key={s.slug} value={`\${system://${s.slug}}`}>
              {s.label}
            </option>
          ))}
          {orphan && <option value={value}>{value}</option>}
        </select>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setCreating((c) => !c)}
          title={t('automations.form.newSecret')}
        >
          ＋
        </Button>
      </div>
      {creating && (
        <div className="flex flex-wrap items-center gap-1 rounded-md border p-2">
          <p className="w-full text-xs text-muted-foreground">
            {t('automations.form.secretSystemHint')}
          </p>
          <Input
            className="h-8 w-28"
            placeholder={t('automations.form.secretSlug')}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
          <Input
            className="h-8 w-28"
            placeholder={t('automations.form.secretLabel')}
            value={labelTxt}
            onChange={(e) => setLabelTxt(e.target.value)}
          />
          <Input
            className="h-8 flex-1"
            type="password"
            placeholder={t('automations.form.secretValue')}
            value={secretValue}
            onChange={(e) => setSecretValue(e.target.value)}
          />
          <Button type="button" size="sm" onClick={doCreate} disabled={createSecret.isPending}>
            {t('automations.form.createSecret')}
          </Button>
        </div>
      )}
    </div>
  )
}

// ─── Éditeur d'en-têtes (partagés par tous les appels/filtres de la règle) ─────

export function HeadersEditor({
  headers,
  setHeaders,
}: {
  headers: HeaderDraft[]
  setHeaders: React.Dispatch<React.SetStateAction<HeaderDraft[]>>
}) {
  const { t } = useTranslation()
  const patch = (i: number, p: Partial<HeaderDraft>) =>
    setHeaders((hs) => hs.map((h, j) => (i === j ? { ...h, ...p } : h)))

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <Label>{t('automations.form.headers')}</Label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            setHeaders((h) => [
              ...h,
              {
                name: '',
                value: '',
                secretRef: '',
                valuePrefix: '',
                isSecret: false,
                required: false,
                enabled: true,
              },
            ])
          }
        >
          {t('automations.form.addHeader')}
        </Button>
      </div>
      {headers.map((h, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2 rounded-md border p-2">
          <Input
            className="w-40"
            placeholder={t('automations.form.headerName')}
            value={h.name}
            onChange={(e) => patch(i, { name: e.target.value })}
          />
          <Input
            className="w-24 font-mono text-xs"
            placeholder={t('automations.form.headerPrefix')}
            title={t('automations.form.headerPrefixHint')}
            value={h.valuePrefix}
            onChange={(e) => patch(i, { valuePrefix: e.target.value })}
          />
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={h.isSecret}
              onChange={(e) => patch(i, { isSecret: e.target.checked })}
            />
            {t('automations.form.secret')}
          </label>
          {h.isSecret ? (
            <SecretPicker value={h.secretRef} onChange={(v) => patch(i, { secretRef: v })} />
          ) : (
            <Input
              className="min-w-0 flex-1"
              placeholder={t('automations.form.headerValue')}
              value={h.value}
              onChange={(e) => patch(i, { value: e.target.value })}
            />
          )}
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={h.enabled}
              onChange={(e) => patch(i, { enabled: e.target.checked })}
            />
            {t('automations.form.enabled')}
          </label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setHeaders((hs) => hs.filter((_, j) => j !== i))}
          >
            ✕
          </Button>
        </div>
      ))}
    </div>
  )
}
