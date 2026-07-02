import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useSetAutoStart } from '../hooks/useCompose'
import ParametersForm from './ParametersForm'
import type { ComposeTemplate } from '../api/types'

interface AutoStartDialogProps {
  template: ComposeTemplate
  open: boolean
  onOpenChange: (open: boolean) => void
}

function initEnvValues(parameters: ComposeTemplate['parameters']): Record<string, string> {
  return Object.fromEntries(parameters.map((p) => [p.key, p.default ?? '']))
}

export default function AutoStartDialog({ template, open, onOpenChange }: AutoStartDialogProps) {
  const { t } = useTranslation()
  const setAutoStart = useSetAutoStart()
  const [envValues, setEnvValues] = useState<Record<string, string>>(() =>
    initEnvValues(template.parameters),
  )

  const missingRequired = template.parameters.some(
    (p) => p.required && !envValues[p.key]?.trim(),
  )

  function handleClose() {
    setEnvValues(initEnvValues(template.parameters))
    onOpenChange(false)
  }

  async function handleSubmit() {
    await setAutoStart.mutateAsync({
      id: template.id,
      body: { enabled: true, env_values: envValues },
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="max-w-[35rem]">
        <DialogHeader>
          <DialogTitle>{t('compose.autoStart.dialogTitle', { name: template.name })}</DialogTitle>
          <p className="text-sm text-muted-foreground">{t('compose.autoStart.dialogHint')}</p>
        </DialogHeader>

        <ParametersForm
          parameters={template.parameters}
          values={envValues}
          onChange={(key, value) => setEnvValues((prev) => ({ ...prev, [key]: value }))}
        />

        <DialogFooter>
          <Button variant="ghost" onClick={handleClose}>
            {t('common.cancel')}
          </Button>
          <Button
            onClick={() => void handleSubmit()}
            disabled={missingRequired || setAutoStart.isPending}
          >
            {t('compose.autoStart.enable')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
