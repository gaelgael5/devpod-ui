import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ExternalLink, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDeleteTestHostLink, useSaveTestHostLink, useTestHostLinks } from './useTestVm'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  wsName: string
  hostName: string
  hostAlias: string
}

/** Gestion des liens (clé → URL) d'un serveur de test — affichés dans son menu ⋮. */
export default function TestHostLinksDialog({
  open, onOpenChange, wsName, hostName, hostAlias,
}: Props) {
  const { t } = useTranslation()
  const { data: links = [] } = useTestHostLinks(wsName, hostName)
  const save = useSaveTestHostLink(wsName, hostName)
  const del = useDeleteTestHostLink(wsName, hostName)
  const [key, setKey] = useState('')
  const [url, setUrl] = useState('')

  function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!key.trim() || !url.trim()) return
    save.mutate(
      { key: key.trim(), url: url.trim() },
      {
        onSuccess: () => {
          setKey('')
          setUrl('')
        },
        onError: (err) =>
          toast.error(err instanceof Error ? err.message : t('workspaces.testHostLinks.saveFailed')),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('workspaces.testHostLinks.title', { alias: hostAlias })}</DialogTitle>
          <DialogDescription>{t('workspaces.testHostLinks.description')}</DialogDescription>
        </DialogHeader>

        {links.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {links.map((link) => (
              <li
                key={link.key}
                className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm"
              >
                <span className="font-medium shrink-0">{link.key}</span>
                <a
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground hover:text-primary hover:underline"
                >
                  {link.url}
                </a>
                <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6 shrink-0 text-destructive hover:text-destructive"
                  aria-label={t('workspaces.testHostLinks.delete', { key: link.key })}
                  onClick={() => del.mutate(link.key)}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">{t('workspaces.testHostLinks.empty')}</p>
        )}

        <form onSubmit={handleSave} className="flex flex-col gap-3 border-t pt-3">
          <div className="grid grid-cols-[1fr_2fr] gap-2">
            <div className="flex flex-col gap-1">
              <Label htmlFor="thl-key">{t('workspaces.testHostLinks.keyLabel')}</Label>
              <Input
                id="thl-key"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder={t('workspaces.testHostLinks.keyPlaceholder')}
                maxLength={50}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="thl-url">{t('workspaces.testHostLinks.urlLabel')}</Label>
              <Input
                id="thl-url"
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="http://192.168.10.201:3000"
              />
            </div>
          </div>
          <Button
            type="submit"
            size="sm"
            className="self-end"
            disabled={!key.trim() || !url.trim() || save.isPending}
          >
            {t('workspaces.testHostLinks.save')}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
