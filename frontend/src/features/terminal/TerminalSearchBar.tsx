import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export interface SearchResults {
  /** Index du résultat courant, `-1` quand le seuil de correspondances est dépassé. */
  resultIndex: number
  resultCount: number
}

interface Props {
  onFind: (term: string, direction: 'next' | 'previous') => void
  onClose: () => void
  results: SearchResults | null
}

/**
 * Barre de recherche du terminal.
 *
 * Séparée du terminal lui-même : elle ne connaît que « chercher » et « fermer »,
 * la mécanique xterm reste dans FullscreenTerminal. Le compteur vient du serveur
 * de recherche (`onDidChangeResults`) et non d'un comptage maison — l'addon
 * plafonne les correspondances et renvoie `-1` au-delà, ce qu'on affiche
 * honnêtement plutôt que d'inventer un total.
 */
export default function TerminalSearchBar({ onFind, onClose, results }: Props) {
  const { t } = useTranslation()
  const [term, setTerm] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // La barre s'ouvre pour être utilisée : le focus y va tout de suite.
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  function submit(direction: 'next' | 'previous') {
    if (term) onFind(term, direction)
  }

  return (
    <div
      className="flex items-center gap-1 border-b border-white/10 bg-[#161628] px-2 py-1.5"
      data-testid="terminal-search"
    >
      <Input
        ref={inputRef}
        value={term}
        onChange={(e) => {
          setTerm(e.target.value)
          // Recherche à la frappe : on repart du début à chaque édition.
          if (e.target.value) onFind(e.target.value, 'next')
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            submit(e.shiftKey ? 'previous' : 'next')
          } else if (e.key === 'Escape') {
            e.preventDefault()
            onClose()
          }
        }}
        placeholder={t('workspaces.terminals.search.placeholder', {
          defaultValue: 'Rechercher…',
        })}
        className="h-7 flex-1 bg-transparent text-xs text-white/90"
        aria-label={t('workspaces.terminals.search.label', {
          defaultValue: 'Rechercher dans le terminal',
        })}
      />
      <span className="min-w-16 text-right text-[11px] tabular-nums text-white/50">
        {results === null || !term
          ? ''
          : results.resultCount === 0
            ? t('workspaces.terminals.search.none', { defaultValue: 'aucun' })
            : results.resultIndex < 0
              ? // L'addon a dépassé son seuil : on ne connaît pas le rang exact.
                t('workspaces.terminals.search.many', {
                  count: results.resultCount,
                  defaultValue: '{{count}}+',
                })
              : `${results.resultIndex + 1}/${results.resultCount}`}
      </span>
      <Button
        size="icon"
        variant="ghost"
        className="h-7 w-7 text-white/70"
        onClick={() => submit('previous')}
        aria-label={t('workspaces.terminals.search.previous', { defaultValue: 'Précédent' })}
      >
        <ChevronUp className="h-3.5 w-3.5" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="h-7 w-7 text-white/70"
        onClick={() => submit('next')}
        aria-label={t('workspaces.terminals.search.next', { defaultValue: 'Suivant' })}
      >
        <ChevronDown className="h-3.5 w-3.5" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="h-7 w-7 text-white/70"
        onClick={onClose}
        aria-label={t('workspaces.terminals.search.close', { defaultValue: 'Fermer la recherche' })}
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}
