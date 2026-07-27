import { useEffect, useState } from 'react'

/** Réagit à une media query CSS. SSR / jsdom sans matchMedia → false (rendu desktop
 *  par défaut, ce qui garde les tests unitaires table-based inchangés). */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}

/** True sous le breakpoint Tailwind `md` (< 768px) : téléphones. */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 767px)')
}
