import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

// Éditeur de liste de noms (outils/resources/prompts) pour la curation par grant.
// Ajoute via Enter ou le bouton ; dédoublonne ; ignore les chaînes vides.
export function ExposeEditor({
  value,
  onChange,
  disabled,
}: {
  value: string[]
  onChange: (next: string[]) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState('')

  const add = () => {
    const name = draft.trim()
    if (!name || value.includes(name)) return
    onChange([...value, name])
    setDraft('')
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex gap-1.5">
        <Input
          value={draft}
          disabled={disabled}
          placeholder={t('mcp.apikeys.exposePlaceholder')}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
          className="h-8"
        />
        <Button type="button" size="sm" variant="secondary" disabled={disabled} onClick={add}>
          {t('mcp.apikeys.exposeAdd')}
        </Button>
      </div>
      {value.length === 0 ? (
        <span className="text-xs text-muted-foreground">{t('mcp.apikeys.exposeEmpty')}</span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {value.map((name) => (
            <Badge key={name} variant="secondary" className="gap-1 font-mono text-xs">
              {name}
              <button
                type="button"
                aria-label={t('mcp.apikeys.exposeRemove')}
                disabled={disabled}
                onClick={() => onChange(value.filter((n) => n !== name))}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}
