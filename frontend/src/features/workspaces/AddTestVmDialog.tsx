import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '@/i18n'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { flattenArgs, type ScriptArg } from '@/features/admin/useProxmoxScript'
import { useTestHypervisors, useTestVmScript, useCreateTestVm } from './useTestVm'

interface Props {
  wsName: string
  open: boolean
  onClose: () => void
}

function argLabel(arg: ScriptArg): string {
  return i18n.language.startsWith('fr') ? arg.label_fr : arg.label_en
}

/** Crée une VM de test attachée au workspace : choix hyperviseur + vmid → script. */
export default function AddTestVmDialog({ wsName, open, onClose }: Props) {
  const { t } = useTranslation()
  const { data: hypervisors = [], isLoading: hypLoading, isError: hypError } = useTestHypervisors(open)
  const [hypervisor, setHypervisor] = useState<string | null>(null)
  const { data: spec, isLoading } = useTestVmScript(open ? hypervisor : null)
  const [vmid, setVmid] = useState('')
  const create = useCreateTestVm()
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [create.logs])

  const idArg: ScriptArg | undefined = spec
    ? flattenArgs(spec.args).find(a => a.identifier)
    : undefined
  // Le backend exige un vmid numérique → on écarte les options non numériques (ex. "auto").
  const vmidOptions = (idArg?.options ?? []).filter(o => /^[0-9]+$/.test(o.value))

  function handleClose() {
    create.reset()
    setHypervisor(null)
    setVmid('')
    onClose()
  }

  const busy = create.running || create.done

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o && !create.running) handleClose() }}>
      <DialogContent className="max-w-[45rem]">
        <DialogHeader>
          <DialogTitle>{t('workspaces.testVm.title')}</DialogTitle>
        </DialogHeader>

        {!busy ? (
          <div className="space-y-4 py-2">
            <div className="space-y-1">
              <Label>{t('workspaces.testVm.hypervisor')}</Label>
              {hypLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('workspaces.testVm.hypLoading')}
                </div>
              ) : hypError ? (
                <p className="text-sm text-destructive">{t('workspaces.testVm.loadError')}</p>
              ) : hypervisors.length === 0 ? (
                <p className="rounded-md border border-dashed bg-muted/40 p-3 text-sm text-muted-foreground">
                  {t('workspaces.testVm.noHypervisors')}
                </p>
              ) : (
                <Select
                  value={hypervisor ?? ''}
                  onValueChange={(v) => { setHypervisor(v); setVmid('') }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('workspaces.testVm.selectHypervisor')} />
                  </SelectTrigger>
                  <SelectContent>
                    {hypervisors.map(h => (
                      <SelectItem key={h.name} value={h.name}>{h.name} — {h.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            {hypervisor && isLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('workspaces.testVm.loading')}
              </div>
            )}

            {idArg && (
              <div className="space-y-1">
                <Label htmlFor="test-vmid">{argLabel(idArg)}</Label>
                {vmidOptions.length > 0 ? (
                  <Select value={vmid} onValueChange={setVmid}>
                    <SelectTrigger id="test-vmid">
                      <SelectValue placeholder={t('workspaces.testVm.selectVmid')} />
                    </SelectTrigger>
                    <SelectContent>
                      {vmidOptions.map(o => (
                        <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id="test-vmid"
                    value={vmid}
                    onChange={e => setVmid(e.target.value)}
                    placeholder="150"
                  />
                )}
              </div>
            )}
          </div>
        ) : (
          <pre ref={logRef} className="max-h-[50vh] overflow-auto whitespace-pre-wrap rounded bg-black/90 p-3 text-xs text-green-200">
            {create.logs || '…'}
          </pre>
        )}

        <DialogFooter>
          {!busy ? (
            <>
              <Button variant="ghost" onClick={handleClose}>{t('workspaces.testVm.cancel')}</Button>
              <Button
                onClick={() => { if (hypervisor && vmid) void create.execute(wsName, hypervisor, vmid) }}
                disabled={!hypervisor || !vmid}
              >
                {t('workspaces.testVm.create')}
              </Button>
            </>
          ) : (
            <Button onClick={handleClose} disabled={create.running}>
              {create.running
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : t('workspaces.testVm.close')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
