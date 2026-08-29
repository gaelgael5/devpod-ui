import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'

export interface OptionRecherchable {
  code: string
  label: string
}

interface Props {
  /** Libellé accessible du champ de recherche. */
  label: string
  options: OptionRecherchable[]
  onSelect: (code: string) => void
  /** Code actuellement retenu, affiché au-dessus de la liste. */
  value?: string
  disabled?: boolean
  /** Au-delà, on n'affiche plus : une liste de 300 lignes ne se lit pas. */
  maxAffichees?: number
}

/** Compare sans accents ni casse : « perou » doit trouver « Pérou ». */
function normalise(texte: string): string {
  return texte
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
}

/**
 * Liste longue rendue cherchable.
 *
 * Une liste deroulante de 250 pays ou de 300 devises se parcourt au pouce sur
 * mobile, et a l'oeil sur un ecran : dans les deux cas c'est fastidieux. Ici on
 * tape trois lettres — du code ou du libelle, avec ou sans accent — et on clique.
 *
 * Volontairement sans dependance : la liste ne s'affiche qu'une fois le champ
 * actif, et se borne pour que le rendu reste court.
 */
export default function SearchableSelect({
  label,
  options,
  onSelect,
  value,
  disabled,
  maxAffichees = 50,
}: Props) {
  const { t } = useTranslation()
  const [filtre, setFiltre] = useState('')
  const [ouvert, setOuvert] = useState(false)

  const trouvees = useMemo(() => {
    const q = normalise(filtre.trim())
    const base = q
      ? options.filter((o) => normalise(o.code).includes(q) || normalise(o.label).includes(q))
      : options
    return base.slice(0, maxAffichees)
  }, [options, filtre, maxAffichees])

  const retenue = options.find((o) => o.code === value)

  function choisir(code: string) {
    onSelect(code)
    setFiltre('')
    setOuvert(false)
  }

  return (
    <div className="relative flex flex-col gap-1">
      <Input
        aria-label={label}
        placeholder={retenue ? `${retenue.code} · ${retenue.label}` : label}
        value={filtre}
        disabled={disabled}
        onChange={(e) => {
          setFiltre(e.target.value)
          setOuvert(true)
        }}
        onFocus={() => setOuvert(true)}
        // Fermeture differee : un clic dans la liste doit avoir le temps
        // d'aboutir avant que le champ ne perde le focus.
        onBlur={() => window.setTimeout(() => setOuvert(false), 150)}
      />

      {ouvert && (
        <ul className="absolute top-full z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border bg-popover shadow-md">
          {trouvees.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">{t('recherche.aucun')}</li>
          )}
          {trouvees.map((o) => (
            <li key={o.code}>
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
                onClick={() => choisir(o.code)}
              >
                <span className="font-mono">{o.code}</span>
                <span className="text-muted-foreground">{o.label}</span>
              </button>
            </li>
          ))}
          {options.length > trouvees.length && (
            <li className="px-3 py-1.5 text-xs text-muted-foreground">
              {t('recherche.affine', { restants: options.length - trouvees.length })}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
