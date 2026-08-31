import { useTranslation } from 'react-i18next'
import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { useHostProfiles } from './useHostProfiles'
import type { OngletProps } from './offerDraft'

/**
 * Ce que l'offre sait faire naitre.
 *
 * `provisioning` sait deja dire qu'il faut ouvrir une machine — VM dediee ou
 * host mutualise — mais pas LAQUELLE. Le profil de host repond : il porte le
 * profil de machine, donc le type d'hyperviseur, donc le script de creation.
 *
 * L'ordre EST la priorite. Un rang porte a part se desynchroniserait de la
 * liste au premier retrait ; ici, remonter une ligne suffit a changer le
 * gabarit essaye en premier. Le numero est affiche parce qu'une liste sans rang
 * ne dit pas que son ordre compte.
 *
 * La liste ne FILTRE pas le placement sur les machines existantes : elle dit
 * seulement quels profils l'offre peut ouvrir.
 */
export default function OfferHostProfilesTab({ brouillon, setBrouillon }: OngletProps) {
  const { t } = useTranslation()
  const { data: catalogue = [] } = useHostProfiles()

  const choisis = brouillon.host_profiles
  // Un profil deja choisi ne doit plus etre proposable : deux fois le meme
  // rendrait la priorite ambigue, et le serveur le refuse.
  const disponibles = catalogue.filter((p) => !choisis.includes(p.slug))

  function libelle(slug: string) {
    return catalogue.find((p) => p.slug === slug)?.label ?? slug
  }

  function poser(profils: string[]) {
    setBrouillon((b) => ({ ...b, host_profiles: profils }))
  }

  function deplacer(index: number, sens: -1 | 1) {
    const cible = index + sens
    if (cible < 0 || cible >= choisis.length) return
    const suite = [...choisis]
    ;[suite[index], suite[cible]] = [suite[cible], suite[index]]
    poser(suite)
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">{t('admin.offers.hostProfilesHelp')}</p>

      {choisis.length === 0 ? (
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          {t('admin.offers.noHostProfile')}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {choisis.map((slug, index) => (
            <li
              key={slug}
              data-testid={`profil-host-${slug}`}
              className="flex items-center gap-3 rounded-md border p-2"
            >
              <span className="w-6 shrink-0 text-center text-sm text-muted-foreground">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm">{libelle(slug)}</span>
              <span className="truncate font-mono text-xs text-muted-foreground">{slug}</span>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-8 w-8 shrink-0"
                aria-label={t('admin.offers.hostProfileUp')}
                disabled={index === 0}
                onClick={() => deplacer(index, -1)}
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-8 w-8 shrink-0"
                aria-label={t('admin.offers.hostProfileDown')}
                disabled={index === choisis.length - 1}
                onClick={() => deplacer(index, 1)}
              >
                <ArrowDown className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-8 w-8 shrink-0"
                aria-label={t('admin.offers.hostProfileRemove')}
                onClick={() => poser(choisis.filter((s) => s !== slug))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="ajout-profil-host">{t('admin.offers.addHostProfile')}</Label>
        <select
          id="ajout-profil-host"
          data-testid="ajout-profil-host"
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
          value=""
          disabled={disponibles.length === 0}
          onChange={(e) => {
            if (e.target.value) poser([...choisis, e.target.value])
          }}
        >
          <option value="">
            {disponibles.length === 0
              ? t('admin.offers.noHostProfileLeft')
              : t('admin.offers.chooseHostProfile')}
          </option>
          {disponibles.map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
