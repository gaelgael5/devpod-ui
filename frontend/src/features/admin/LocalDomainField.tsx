import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useLocalDomain, useSaveLocalDomain } from './useLocalDomain'

/** Réglage du domaine DNS local utilisé pour re-résoudre l'IP DHCP des VM de test. */
export default function LocalDomainField() {
  const { t } = useTranslation()
  const { data } = useLocalDomain()
  const save = useSaveLocalDomain()
  // État local non initialisé tant que l'utilisateur n'a pas tapé → valeur dérivée
  // du serveur (évite un setState dans un effet).
  const [edited, setEdited] = useState<string | null>(null)
  const value = edited ?? data?.local_domain ?? ''

  function handleSave() {
    save.mutate(value.trim(), {
      onSuccess: () => { setEdited(null); toast.success(t('admin.localDomain.saved')) },
    })
  }

  const dirty = data != null && value.trim() !== data.local_domain

  return (
    <div className="mb-6 rounded-lg border bg-card p-4">
      <Label htmlFor="local-domain">{t('admin.localDomain.title')}</Label>
      <p className="mb-2 text-xs text-muted-foreground">{t('admin.localDomain.hint')}</p>
      <div className="flex items-center gap-2">
        <Input
          id="local-domain"
          value={value}
          onChange={(e) => setEdited(e.target.value)}
          placeholder="home.lan"
          className="max-w-xs font-mono"
        />
        <Button size="sm" onClick={handleSave} disabled={!dirty || save.isPending}>
          {t('admin.localDomain.save')}
        </Button>
      </div>
    </div>
  )
}
