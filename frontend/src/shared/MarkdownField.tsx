import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

interface Props {
  id: string
  label: string
  value: string
  onChange: (valeur: string) => void
  rows?: number
}

/**
 * Saisie markdown avec apercu.
 *
 * Deux onglets plutot qu'un rendu cote a cote : sur mobile, deux colonnes
 * donnent deux zones trop etroites pour l'une comme pour l'autre.
 *
 * L'apercu utilise le meme rendu que l'affichage client (`react-markdown` +
 * `remark-gfm`) : ce que l'administrateur voit ici est ce qui sortira, et non
 * une approximation.
 */
export default function MarkdownField({ id, label, value, onChange, rows = 5 }: Props) {
  const { t } = useTranslation()
  const [apercu, setApercu] = useState(false)

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>{label}</Label>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 text-xs"
          onClick={() => setApercu((a) => !a)}
        >
          {t(apercu ? 'markdown.edit' : 'markdown.preview')}
        </Button>
      </div>

      {apercu ? (
        <div
          className="prose prose-sm dark:prose-invert min-h-24 max-w-none rounded-md border p-3"
          data-testid={`${id}-apercu`}
        >
          {value.trim() ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
          ) : (
            <p className="text-muted-foreground">{t('markdown.empty')}</p>
          )}
        </div>
      ) : (
        <textarea
          id={id}
          className="min-h-24 rounded-md border border-input bg-transparent p-2 font-mono text-sm"
          rows={rows}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  )
}
