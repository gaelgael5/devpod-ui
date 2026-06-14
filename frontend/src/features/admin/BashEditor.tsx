import Prism from 'prismjs'
import 'prismjs/components/prism-bash'
import type { ReactNode } from 'react'

type PrismToken = Prism.Token | string

const COLORS: Record<string, string> = {
  comment:     '#6a9955',
  shebang:     '#6a9955',
  important:   '#569cd6',
  keyword:     '#569cd6',
  string:      '#ce9178',
  number:      '#b5cea8',
  boolean:     '#569cd6',
  variable:    '#9cdcfe',
  operator:    '#d4d4d4',
  function:    '#dcdcaa',
  builtin:     '#dcdcaa',
  punctuation: '#d4d4d4',
}

function renderTokens(tokens: PrismToken[]): ReactNode {
  return tokens.map((token, i) => {
    if (typeof token === 'string') return token
    const color = COLORS[token.type] ?? '#d4d4d4'
    const inner = Array.isArray(token.content)
      ? renderTokens(token.content as PrismToken[])
      : renderTokens([token.content as PrismToken])
    return <span key={i} style={{ color }}>{inner}</span>
  })
}

function highlight(code: string): ReactNode {
  const grammar = Prism.languages.bash
  if (!grammar) return code
  try {
    return renderTokens(Prism.tokenize(code, grammar))
  } catch {
    return code
  }
}

// Styles partagés pré/textarea — doivent être identiques pour l'alignement
const CODE_STYLE: React.CSSProperties = {
  fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
  fontSize: '0.8125rem',
  lineHeight: '1.6',
  padding: '0.75rem',
  margin: 0,
  tabSize: 2,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
  overflowWrap: 'break-word',
}

interface BashEditorProps {
  value: string
  onChange: (value: string) => void
}

export default function BashEditor({ value, onChange }: BashEditorProps) {
  return (
    <div
      className="overflow-auto rounded-md border border-input bg-zinc-950 shadow-sm focus-within:ring-1 focus-within:ring-ring"
      style={{ minHeight: '420px', maxHeight: '62vh' }}
    >
      {/* Grid trick : pré et textarea dans la même cellule — la plus grande détermine la hauteur */}
      <div style={{ display: 'grid', minHeight: '420px' }}>
        <pre
          aria-hidden
          style={{
            ...CODE_STYLE,
            gridArea: '1/1',
            color: '#d4d4d4',
            pointerEvents: 'none',
            userSelect: 'none',
          }}
        >
          {highlight(value)}
          {/* newline pour éviter l'effondrement de la dernière ligne vide */}
          {'\n'}
        </pre>
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          autoCapitalize="off"
          autoComplete="off"
          autoCorrect="off"
          style={{
            ...CODE_STYLE,
            gridArea: '1/1',
            background: 'transparent',
            border: 'none',
            color: 'transparent',
            caretColor: '#fff',
            resize: 'none',
            outline: 'none',
            zIndex: 1,
          }}
        />
      </div>
    </div>
  )
}
