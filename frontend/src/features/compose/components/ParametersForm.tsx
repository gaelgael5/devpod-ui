import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import type { ComposeParam } from '../api/types'

interface ParametersFormProps {
  parameters: ComposeParam[]
  values: Record<string, string>
  onChange: (key: string, value: string) => void
  errors?: Record<string, string>
}

function FieldWrapper({
  param,
  children,
  error,
}: {
  param: ComposeParam
  children: React.ReactNode
  error?: string
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={`param-${param.key}`} className="flex gap-0.5">
        {param.label}
        {param.required && <span className="text-destructive">*</span>}
      </Label>
      {param.description && (
        <p className="text-xs text-muted-foreground">{param.description}</p>
      )}
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

function StringField({
  param,
  value,
  onChange,
}: {
  param: ComposeParam
  value: string
  onChange: (v: string) => void
}) {
  return (
    <Input
      id={`param-${param.key}`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

function NumberField({
  param,
  value,
  onChange,
}: {
  param: ComposeParam
  value: string
  onChange: (v: string) => void
}) {
  return (
    <Input
      id={`param-${param.key}`}
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

function BoolField({
  param,
  value,
  onChange,
}: {
  param: ComposeParam
  value: string
  onChange: (v: string) => void
}) {
  return (
    <RadioGroup
      id={`param-${param.key}`}
      value={value}
      onValueChange={onChange}
      className="flex gap-4"
    >
      <div className="flex items-center gap-1.5">
        <RadioGroupItem value="true" id={`param-${param.key}-true`} />
        <Label htmlFor={`param-${param.key}-true`}>Oui</Label>
      </div>
      <div className="flex items-center gap-1.5">
        <RadioGroupItem value="false" id={`param-${param.key}-false`} />
        <Label htmlFor={`param-${param.key}-false`}>Non</Label>
      </div>
    </RadioGroup>
  )
}

function EnumField({
  param,
  value,
  onChange,
}: {
  param: ComposeParam
  value: string
  onChange: (v: string) => void
}) {
  const options = param.options ?? []
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={`param-${param.key}`}>
        <SelectValue placeholder="Choisir…" />
      </SelectTrigger>
      <SelectContent>
        {options.map((opt) => (
          <SelectItem key={opt} value={opt}>
            {opt}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function SecretField({
  param,
  value,
  onChange,
}: {
  param: ComposeParam
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="space-y-1">
      <Input
        id={`param-${param.key}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="${vault://bloc/nom}"
      />
      {param.secret_ref_hint && (
        <p className="text-xs text-muted-foreground">{param.secret_ref_hint}</p>
      )}
    </div>
  )
}

function ParamWidget({
  param,
  value,
  onChange,
}: {
  param: ComposeParam
  value: string
  onChange: (v: string) => void
}) {
  switch (param.type) {
    case 'number':
    case 'port':
      return <NumberField param={param} value={value} onChange={onChange} />
    case 'bool':
      return <BoolField param={param} value={value} onChange={onChange} />
    case 'enum':
      return <EnumField param={param} value={value} onChange={onChange} />
    case 'secret':
      return <SecretField param={param} value={value} onChange={onChange} />
    default:
      return <StringField param={param} value={value} onChange={onChange} />
  }
}

export default function ParametersForm({
  parameters,
  values,
  onChange,
  errors,
}: ParametersFormProps) {
  return (
    <div className="space-y-4">
      {parameters.map((param) => (
        <FieldWrapper key={param.key} param={param} error={errors?.[param.key]}>
          <ParamWidget
            param={param}
            value={values[param.key] ?? ''}
            onChange={(v) => onChange(param.key, v)}
          />
        </FieldWrapper>
      ))}
    </div>
  )
}
