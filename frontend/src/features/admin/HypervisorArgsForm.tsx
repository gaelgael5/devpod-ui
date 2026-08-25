import { useTranslation } from 'react-i18next'
import i18n from '@/i18n'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import type { ScriptArg, ScriptSubArg, ScriptArgOrSub } from './useProxmoxScript'

function argLabel(arg: ScriptArg | ScriptSubArg): string {
  return i18n.language.startsWith('fr') ? arg.label_fr : arg.label_en
}

function argDescription(arg: ScriptArg): string | undefined {
  return i18n.language.startsWith('fr') ? arg.description_fr : arg.description_en
}

function Field({ arg, value, onChange, templating }: {
  arg: ScriptArg
  value: string
  onChange: (v: string) => void
  /** Rappelle les variables acceptees dans les valeurs (profils de machine). */
  templating?: boolean
}) {
  const { t } = useTranslation()
  const id = `arg-${arg.arg}`
  // Le rappel ne vaut que pour une saisie libre : sur une liste fermee ou un
  // entier, aucune valeur templatee ne serait acceptee.
  const saisieLibre = !arg.options?.length && arg.type !== 'integer'
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>
        {argLabel(arg)}
        {arg.required && <span className="text-destructive"> *</span>}
        {/* Regle de templating rappelee AU CHAMP concerne : elle ne vaut que
            pour les valeurs textuelles, et un rappel global en tete du
            formulaire se lit rarement au moment ou l'on saisit. */}
        {templating && saisieLibre && (
          <span className="ml-2 font-normal text-xs text-muted-foreground">
            {t('admin.argsForm.templating')}
          </span>
        )}
      </Label>
      {arg.options && arg.options.length > 0 ? (
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger id={id}><SelectValue /></SelectTrigger>
          <SelectContent>
            {arg.options.map(o => (
              <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          id={id}
          type={arg.type === 'integer' ? 'number' : 'text'}
          value={value}
          onChange={e => onChange(e.target.value)}
        />
      )}
      {argDescription(arg) && (
        <p className="text-xs text-muted-foreground">{argDescription(arg)}</p>
      )}
    </div>
  )
}

interface Props {
  args: ScriptArgOrSub[]
  values: Record<string, string>
  onChange: (key: string, value: string) => void
  /** Masque l'arg marqué `identifier` (vmid) — non pré-remplissable. */
  excludeIdentifier?: boolean
  /**
   * Rappelle, à côté de chaque libellé, les variables acceptées dans la valeur.
   * Réservé aux profils de machine : à la création d'une VM les valeurs sont
   * déjà résolues, la mention n'y voudrait rien dire.
   */
  templating?: boolean
}

/**
 * Formulaire contrôlé pour les `args` d'une spec d'hyperviseur. Rend les champs
 * string/integer/select et les groupes `sub`. Sans résolution dynamique : utilise
 * les options statiques de la spec.
 */
export default function HypervisorArgsForm({
  args,
  values,
  onChange,
  excludeIdentifier,
  templating,
}: Props) {
  const hidden = (a: ScriptArg) => Boolean(excludeIdentifier && a.identifier)
  return (
    <div className="space-y-3">
      {args.map((a, i) => {
        if (a.type === 'sub') {
          const visible = a.args.filter(arg => !hidden(arg))
          if (visible.length === 0) return null
          return (
            <fieldset key={i} className="space-y-3 rounded-md border p-3">
              <legend className="px-1 text-xs text-muted-foreground">{argLabel(a)}</legend>
              {visible.map(arg => (
                <Field
                  key={arg.arg}
                  arg={arg}
                  value={values[arg.arg] ?? ''}
                  onChange={v => onChange(arg.arg, v)}
                  templating={templating}
                />
              ))}
            </fieldset>
          )
        }
        if (hidden(a)) return null
        return (
          <Field
            key={a.arg}
            arg={a}
            value={values[a.arg] ?? ''}
            onChange={v => onChange(a.arg, v)}
            templating={templating}
          />
        )
      })}
    </div>
  )
}
