import Prism from 'prismjs'
import 'prismjs/components/prism-json'
import type { ReactNode } from 'react'

type PrismToken = Prism.Token | string

// Palette VS Code Dark+
const COLORS: Record<string, string> = {
  property:    '#9cdcfe',
  string:      '#ce9178',
  number:      '#b5cea8',
  boolean:     '#569cd6',
  keyword:     '#569cd6',
  null:        '#569cd6',
  punctuation: '#d4d4d4',
  operator:    '#d4d4d4',
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
  const grammar = Prism.languages.json
  if (!grammar) return code
  try {
    return renderTokens(Prism.tokenize(code, grammar))
  } catch {
    return code
  }
}

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

interface JsonEditorProps {
  value: string
  onChange: (value: string) => void
  minHeight?: string
}

export default function JsonEditor({ value, onChange, minHeight = '180px' }: JsonEditorProps) {
  return (
    <div
      className="overflow-auto rounded-md border border-input bg-zinc-950 shadow-sm focus-within:ring-1 focus-within:ring-ring"
      style={{ minHeight, maxHeight: '50vh' }}
    >
      <div style={{ display: 'grid', minHeight }}>
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
