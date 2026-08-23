import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, Eye } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  useRevealTestHostRootPassword, useUpdateTestHostConn, type TestHost,
} from './useTestVm'

interface Props {
  wsName: string
  host: TestHost
  onClose: () => void
}

/**
 * Édite les paramètres de connexion MÉMORISÉS d'une machine de test :
 * host, username, et mot de passe root. Le mot de passe stocké n'est jamais
 * pré-rempli : il faut le révéler derrière le PIN vault (comme le reveal du mot
 * de passe console admin). Un champ laissé vide = mot de passe inchangé.
 */
export default function TestHostConnDialog({ wsName, host, onClose }: Props) {
  const { t } = useTranslation()
  const update = useUpdateTestHostConn(wsName)
  const reveal = useRevealTestHostRootPassword(wsName)

  const [username, setUsername] = useState(host.user ?? 'root')
  const [hostAddr, setHostAddr] = useState(host.ip)
  const [password, setPassword] = useState('')
  const [pinOpen, setPinOpen] = useState(false)
  const [pin, setPin] = useState('')
  // Vrai une fois le mot de passe révélé/saisi : on rend le champ lisible.
  const [pwVisible, setPwVisible] = useState(false)

  function submitPin() {
    reveal.mutate(
      { hostName: host.name, pin },
      {
        onSuccess: (res) => {
          setPassword(res.value)
          setPwVisible(true)
          setPin('')
          setPinOpen(false)
        },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : t('workspaces.testHostConn.revealFailed')),
      },
    )
  }

  function copyPassword() {
    if (!password) return
    navigator.clipboard.writeText(password).then(
      () => toast.success(t('workspaces.testHostConn.passwordCopied')),
      () => toast.error(t('workspaces.testHostConn.copyFailed')),
    )
  }

  function handleSave() {
    update.mutate(
      {
        hostName: host.name,
        username: username.trim(),
        host: hostAddr.trim(),
        // Champ vide = ne pas toucher au secret stocké.
        password: password === '' ? undefined : password,
      },
      {
        onSuccess: () => { toast.success(t('workspaces.testHostConn.saved')); onClose() },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : t('workspaces.testHostConn.saveFailed')),
      },
    )
  }

  const canSave = !!username.trim() && !!hostAddr.trim() && !update.isPending

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('workspaces.testHostConn.title', { alias: host.alias })}</DialogTitle>
          <DialogDescription>{t('workspaces.testHostConn.description')}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 py-1">
          <div className="flex flex-col gap-1">
            <Label htmlFor="thc-username">{t('workspaces.testHostConn.username')}</Label>
            <Input
              id="thc-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label htmlFor="thc-host">{t('workspaces.testHostConn.host')}</Label>
            <Input
              id="thc-host"
              value={hostAddr}
              onChange={(e) => setHostAddr(e.target.value)}
              placeholder="192.168.10.219"
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label htmlFor="thc-password">{t('workspaces.testHostConn.password')}</Label>
            <div className="flex items-center gap-2">
              <Input
                id="thc-password"
                type={pwVisible ? 'text' : 'password'}
                value={password}
                onChange={(e) => { setPassword(e.target.value); setPwVisible(true) }}
                placeholder={t('workspaces.testHostConn.passwordPlaceholder')}
                autoComplete="new-password"
                className="font-mono"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9 shrink-0"
                disabled={!password}
                aria-label={t('workspaces.testHostConn.copyPassword')}
                onClick={copyPassword}
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>

            {!pinOpen ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-1 self-start"
                onClick={() => setPinOpen(true)}
              >
                <Eye className="mr-1.5 h-3.5 w-3.5" />
                {t('workspaces.testHostConn.reveal')}
              </Button>
            ) : (
              <div className="mt-1 flex items-center gap-2">
                <Input
                  type="password"
                  inputMode="numeric"
                  maxLength={6}
                  autoFocus
                  value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') { e.preventDefault(); if (pin.length === 6) submitPin() }
                  }}
                  placeholder={t('workspaces.testHostConn.pinPlaceholder')}
                  className="w-40"
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={pin.length !== 6 || reveal.isPending}
                  onClick={submitPin}
                >
                  {t('workspaces.testHostConn.revealConfirm')}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => { setPinOpen(false); setPin('') }}
                >
                  {t('workspaces.testHostConn.cancel')}
                </Button>
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('workspaces.testHostConn.cancel')}
          </Button>
          <Button size="sm" disabled={!canSave} onClick={handleSave}>
            {update.isPending ? '…' : t('workspaces.testHostConn.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
