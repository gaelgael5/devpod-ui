import { useTranslation } from 'react-i18next'
import { useLanguageChoice } from '@/shared/hooks/useLanguageChoice'
import type { Culture } from '@/features/profile/useCulture'

const NOMS: Record<Culture, string> = { fr: 'Français', en: 'English' }

interface Props {
  /** `false` sur une page publique : le choix ne va nulle part ailleurs que
   *  dans le `localStorage` d'i18next — il n'y a pas de compte où le ranger. */
  persist: boolean
  className?: string
}

/**
 * Sélecteur de langue, utilisable avec ou sans compte.
 *
 * Un `<select>` natif plutôt qu'une bascule : à deux langues une bascule
 * suffirait, mais elle devient un piège dès la troisième — et `supportedLngs`
 * est fait pour grandir.
 */
export default function LanguageSelect({ persist, className }: Props) {
  const { t } = useTranslation()
  const { current, available, choose } = useLanguageChoice({ persist })

  return (
    <select
      aria-label={t('nav.language')}
      value={current}
      onChange={(e) => choose(e.target.value as Culture)}
      className={`h-9 rounded-md border bg-background px-2 text-sm ${className ?? ''}`}
    >
      {available.map((langue) => (
        <option key={langue} value={langue}>
          {NOMS[langue]}
        </option>
      ))}
    </select>
  )
}
