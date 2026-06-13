import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { useBootstrapSsh, useProxmoxNodes, type HostConfig } from './useHosts'

interface Props {
  host: HostConfig
  open: boolean
  onClose: () => void
}

export default function BootstrapSshDialog({ host, open, onClose }: Props) {
  const { t } = useTranslation()
  const { data: nodes = [] } = useProxmoxNodes()
  const bootstrap = useBootstrapSsh()
  const [address, setAddress] = useState(host.address ?? '')
  const [proxmoxNode, setProxmoxNode] = useState('')

  useEffect(() => {
    if (nodes.length === 1 && !proxmoxNode) setProxmoxNode(nodes[0].name)
  }, [nodes])

  function handleClose() {
    setAddress(host.address ?? '')
    setProxmoxNode('')
    bootstrap.reset()
    onClose()
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    bootstrap.mutate(
      { name: host.name, payload: { address, proxmox_node: proxmoxNode } },
      { onSuccess: handleClose }
    )
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('admin.bootstrap.title', { name: host.name })}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t('admin.bootstrap.description')}</p>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bs-address">{t('admin.bootstrap.address')}</Label>
            <Input
              id="bs-address"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="debian@192.168.1.50"
              required
            />
          </div>
          {nodes.length !== 1 && (
            <div className="flex flex-col gap-1.5">
              <Label>{t('admin.bootstrap.proxmoxNode')}</Label>
              <Select value={proxmoxNode} onValueChange={setProxmoxNode}>
                <SelectTrigger>
                  <SelectValue placeholder={t('admin.bootstrap.selectNode')} />
                </SelectTrigger>
                <SelectContent>
                  {nodes.map((n) => (
                    <SelectItem key={n.name} value={n.name}>
                      {n.name} ({n.address})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {bootstrap.isError && (
            <p className="text-sm text-destructive">
              {bootstrap.error instanceof Error ? bootstrap.error.message : t('errors.generic')}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose}>
              {t('workspaces.confirm.cancel')}
            </Button>
            <Button type="submit" disabled={bootstrap.isPending || !proxmoxNode}>
              {bootstrap.isPending ? t('admin.bootstrap.configuring') : t('admin.bootstrap.configure')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
