import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import HypervisorArgsForm from './HypervisorArgsForm'
import {
  useAdminHypervisorTypes, useSaveTestHostParams, type HypervisorTypeConfig,
} from './useAdminHypervisorTypes'
import { useTypeScriptSpec, flattenArgs, type ScriptSpec } from './useProxmoxScript'

interface Props {
  open: boolean
  onClose: () => void
}

/**
 * Éditeur des valeurs — son `key` (= type sélectionné) garantit un state neuf à
 * chaque changement de type, sans `useEffect` de réinitialisation.
 */
function ParamsEditor({ typeName, spec, initial, onClose }: {
  typeName: string
  spec: ScriptSpec
  initial: Record<string, string>
  onClose: () => void
}) {
  const { t } = useTranslation()
  const save = useSaveTestHostParams()
  const [values, setValues] = useState<Record<string, string>>(() => initial)

  function set(key: string, value: string) {
    setValues(v => ({ ...v, [key]: value }))
  }

  function handleSave() {
    const idArg = flattenArgs(spec.args).find(a => a.identifier)?.arg
    const params = Object.fromEntries(
      Object.entries(values).filter(([k]) => k !== idArg),
    )
    save.mutate({ name: typeName, params }, {
      onSuccess: () => { toast.success(t('admin.testHostParams.saved')); onClose() },
    })
  }

  return (
    <>
      <p className="rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
        {t('admin.testHostParams.varsHint')}
      </p>
      <HypervisorArgsForm args={spec.args} values={values} onChange={set} excludeIdentifier />
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>{t('admin.testHostParams.cancel')}</Button>
        <Button onClick={handleSave} disabled={save.isPending}>
          {save.isPending ? '…' : t('admin.testHostParams.save')}
        </Button>
      </DialogFooter>
    </>
  )
}

/** Paramétrage des valeurs par défaut d'un host de test, par type d'hyperviseur. */
export default function TestHostParamsDialog({ open, onClose }: Props) {
  const { t } = useTranslation()
  const { typesQuery } = useAdminHypervisorTypes()
  const types: HypervisorTypeConfig[] = typesQuery.data ?? []
  const [selected, setSelected] = useState<string | null>(null)
  const { data: spec, isLoading, error } = useTypeScriptSpec(open ? selected : null)

  const selectedType = useMemo(
    () => (typesQuery.data ?? []).find(ty => ty.name === selected),
    [typesQuery.data, selected],
  )

  const initial = useMemo<Record<string, string>>(() => {
    if (!spec) return {}
    const base: Record<string, string> = {}
    for (const a of flattenArgs(spec.args)) {
      base[a.arg] = a.default !== undefined ? String(a.default) : (a.options?.[0]?.value ?? '')
    }
    return { ...base, ...(selectedType?.test_host_params ?? {}) }
  }, [spec, selectedType])

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('admin.testHostParams.title')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1">
            <Label>{t('admin.testHostParams.type')}</Label>
            <Select value={selected ?? ''} onValueChange={setSelected}>
              <SelectTrigger>
                <SelectValue placeholder={t('admin.testHostParams.selectType')} />
              </SelectTrigger>
              <SelectContent>
                {types.map(ty => (
                  <SelectItem key={ty.name} value={ty.name}>{ty.label || ty.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {selected && isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('admin.testHostParams.loading')}
            </div>
          )}
          {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
          {spec && selected && (
            <ParamsEditor key={selected} typeName={selected} spec={spec} initial={initial} onClose={onClose} />
          )}
        </div>
        {!spec && (
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>{t('admin.testHostParams.cancel')}</Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}
