import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { OngletProps } from './offerDraft'

/**
 * Variables personnalisées de l'offre.
 *
 * Un jeu de clés/valeurs libre (gabarit de VM, capacité du host…), injecté dans
 * les événements `debut_essai`/`activation` à la souscription : c'est par lui
 * que l'offre paramètre le script de provisioning sans que le portail connaisse
 * chaque paramètre à l'avance.
 *
 * La clé d'une variable posée ne se retape pas : la renommer, c'est une autre
 * variable — on supprime et on repose. Seule la VALEUR reste éditable en place.
 * Une clé déjà posée est refusée à l'ajout plutôt qu'écrasée en silence : un
 * gabarit de VM remplacé sans bruit se découvrirait au provisionnement suivant.
 */
export default function OfferVariablesTab({ brouillon, setBrouillon }: OngletProps) {
  const { t } = useTranslation()
  const [clef, setClef] = useState('')
  const [valeur, setValeur] = useState('')
  const [doublon, setDoublon] = useState(false)

  const entrees = Object.entries(brouillon.variables)

  function poser(variables: Record<string, string>) {
    setBrouillon((b) => ({ ...b, variables }))
  }

  function ajouter() {
    const nom = clef.trim()
    if (!nom) return
    if (nom in brouillon.variables) {
      setDoublon(true)
      return
    }
    poser({ ...brouillon.variables, [nom]: valeur })
    setClef('')
    setValeur('')
    setDoublon(false)
  }

  function retirer(nom: string) {
    poser(Object.fromEntries(entrees.filter(([n]) => n !== nom)))
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">{t('admin.offers.variablesHelp')}</p>

      {entrees.length === 0 ? (
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          {t('admin.offers.noVariable')}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {entrees.map(([nom, val]) => (
            <li
              key={nom}
              data-testid={`variable-${nom}`}
              className="flex items-center gap-3 rounded-md border p-2"
            >
              <span className="min-w-0 flex-1 truncate font-mono text-sm">{nom}</span>
              <Input
                aria-label={t('admin.offers.variableValueOf', { name: nom })}
                className="h-8 max-w-52"
                value={val}
                onChange={(e) => poser({ ...brouillon.variables, [nom]: e.target.value })}
              />
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-8 w-8 shrink-0"
                aria-label={t('admin.offers.variableRemove')}
                onClick={() => retirer(nom)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="variable-clef">{t('admin.offers.variableKey')}</Label>
          <Input
            id="variable-clef"
            className="h-9 font-mono"
            value={clef}
            onChange={(e) => {
              setClef(e.target.value)
              setDoublon(false)
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="variable-valeur">{t('admin.offers.variableValue')}</Label>
          <Input
            id="variable-valeur"
            className="h-9"
            value={valeur}
            onChange={(e) => setValeur(e.target.value)}
          />
        </div>
        <Button type="button" variant="outline" disabled={!clef.trim()} onClick={ajouter}>
          {t('admin.offers.addVariable')}
        </Button>
      </div>

      {doublon && (
        <p className="text-sm text-destructive">{t('admin.offers.variableExists')}</p>
      )}
    </div>
  )
}
