import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Props {
  children: string
  /** Rendu INLINE : les paragraphes ne créent pas de bloc. Pour un titre. */
  inline?: boolean
  className?: string
}

/**
 * Affichage d'un contenu markdown, côté client.
 *
 * Même moteur que l'aperçu de `MarkdownField` (`react-markdown` + `remark-gfm`),
 * et c'est le point : ce que l'administrateur voit en écrivant est ce que le
 * visiteur verra. Deux rendus différents feraient de l'aperçu un mensonge.
 *
 * Pas de `rehype-raw` : le HTML brut d'un champ d'administration n'est pas
 * interprété. `react-markdown` échappe par défaut, et on ne lui retire pas cette
 * garantie pour un gain cosmétique.
 *
 * `inline` sert aux titres : `react-markdown` enveloppe tout dans un `<p>`, ce
 * qui casserait la typographie d'un `<h2>` et produirait un bloc dans un bloc.
 */
export default function Markdown({ children, inline = false, className }: Props) {
  const composants = inline
    ? { p: ({ children: enfants }: { children?: ReactNode }) => <>{enfants}</> }
    : undefined

  return (
    <div className={inline ? className : `prose prose-sm dark:prose-invert max-w-none ${className ?? ''}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={composants}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
