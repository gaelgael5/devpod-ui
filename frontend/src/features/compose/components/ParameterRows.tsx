import { Plus, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { ComposeParam, ComposeParamType } from '../api/types'

const PARAM_TYPES: ComposeParamType[] = ['string', 'number', 'bool', 'enum', 'port', 'secret']

function emptyParam(): ComposeParam {
  return { key: '', label: '', type: 'string', required: false, default: null, options: null }
}

interface ParameterRowsProps {
  params: ComposeParam[]
  onChange: (params: ComposeParam[]) => void
}

export default function ParameterRows({ params, onChange }: ParameterRowsProps) {
  const { t } = useTranslation()

  function updateParam(index: number, patch: Partial<ComposeParam>) {
    onChange(params.map((p, i) => (i === index ? { ...p, ...patch } : p)))
  }

  function addParam() {
    onChange([...params, emptyParam()])
  }

  function removeParam(index: number) {
    onChange(params.filter((_, i) => i !== index))
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <Label>{t('compose.form.parameters')}</Label>
        <Button type="button" size="sm" variant="outline" onClick={addParam}>
          <Plus className="mr-1 h-3 w-3" />
          {t('compose.form.addParam')}
        </Button>
      </div>
      {params.map((param, i) => (
        <div key={i} className="rounded-md border p-3 flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">{t('compose.form.paramKey')}</Label>
              <Input
                value={param.key}
                onChange={(e) => updateParam(i, { key: e.target.value })}
                placeholder="MY_VAR"
                className="h-7 text-xs"
              />
            </div>
            <div>
              <Label className="text-xs">{t('compose.form.paramLabel')}</Label>
              <Input
                value={param.label}
                onChange={(e) => updateParam(i, { label: e.target.value })}
                placeholder="My variable"
                className="h-7 text-xs"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">{t('compose.form.paramType')}</Label>
              <Select
                value={param.type}
                onValueChange={(v) =>
                  updateParam(i, {
                    type: v as ComposeParamType,
                    options: v === 'enum' ? (param.options ?? []) : null,
                  })
                }
              >
                <SelectTrigger className="h-7 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PARAM_TYPES.map((pt) => (
                    <SelectItem key={pt} value={pt}>{pt}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">{t('compose.form.paramDefault')}</Label>
              <Input
                value={param.default ?? ''}
                onChange={(e) => updateParam(i, { default: e.target.value || null })}
                className="h-7 text-xs"
              />
            </div>
          </div>
          {param.type === 'enum' && (
            <div>
              <Label className="text-xs">{t('compose.form.paramOptions')}</Label>
              <Input
                value={(param.options ?? []).join(',')}
                onChange={(e) =>
                  updateParam(i, {
                    options: e.target.value
                      ? e.target.value.split(',').map((s) => s.trim())
                      : [],
                  })
                }
                placeholder="opt1,opt2,opt3"
                className="h-7 text-xs"
              />
            </div>
          )}
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-1 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={param.required}
                onChange={(e) => updateParam(i, { required: e.target.checked })}
                className="h-3 w-3"
              />
              {t('compose.form.paramRequired')}
            </label>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-6 text-xs text-destructive hover:text-destructive"
              onClick={() => removeParam(i)}
            >
              <X className="mr-1 h-3 w-3" />
              {t('compose.form.removeParam')}
            </Button>
          </div>
        </div>
      ))}
    </div>
  )
}
