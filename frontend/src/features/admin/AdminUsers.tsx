import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useTermixInstances } from './useTermixInstances'
import {
  useAdminUsers,
  useHostGrants,
  useSetHostGrants,
  useSshHosts,
  type AdminUser,
  type SshHost,
} from './useAdminUsers'

// Radix interdit une valeur vide sur SelectItem : sentinelle pour « héritage défaut ».
const INHERIT = '__inherit__'

/** Sélecteur d'instance Termix pour un user (rattachement explicite ou héritage). */
function InstanceSelect({ user }: { user: AdminUser }) {
  const { t } = useTranslation()
  const { listQuery } = useTermixInstances()
  const { setInstance } = useAdminUsers()
  const instances = listQuery.data ?? []

  return (
    <Select
      value={user.termix_instance_id ?? INHERIT}
      onValueChange={(v) =>
        setInstance.mutate({ login: user.login, instanceId: v === INHERIT ? null : v })
      }
    >
      <SelectTrigger className="h-8 w-56">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={INHERIT}>{t('admin.users.inheritDefault')}</SelectItem>
        {instances.map((i) => (
          <SelectItem key={i.id} value={i.id}>
            {i.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** Cases à cocher des hosts, état local initialisé une fois les grants chargés
 *  (monté seulement quand `initialChecked` est connu → pas de setState en effet). */
function GrantsForm({
  login,
  hosts,
  initialChecked,
  onClose,
}: {
  login: string
  hosts: SshHost[]
  initialChecked: string[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const setGrants = useSetHostGrants()
  const [checked, setChecked] = useState<Set<string>>(() => new Set(initialChecked))

  function toggle(wsId: string) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(wsId)) next.delete(wsId)
      else next.add(wsId)
      return next
    })
  }

  return (
    <>
      {hosts.length === 0 ? (
        <p className="text-muted-foreground">{t('admin.users.noHosts')}</p>
      ) : (
        <div className="max-h-72 overflow-y-auto rounded-md border">
          {hosts.map((h) => (
            <label
              key={h.ws_id}
              className="flex cursor-pointer items-center gap-3 border-b px-3 py-2 last:border-0 hover:bg-muted/50"
            >
              <input
                type="checkbox"
                checked={checked.has(h.ws_id)}
                onChange={() => toggle(h.ws_id)}
                aria-label={h.ws_id}
              />
              <span className="font-mono text-xs">{h.ws_id}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {h.login} · {h.host_name ?? '—'}:{h.ssh_port ?? '—'}
              </span>
            </label>
          ))}
        </div>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          {t('workspaces.confirm.cancel')}
        </Button>
        <Button
          onClick={() => setGrants.mutate({ login, hosts: [...checked] }, { onSuccess: onClose })}
          disabled={setGrants.isPending}
        >
          {t('admin.form.save')}
        </Button>
      </DialogFooter>
    </>
  )
}

/** Dialogue sélecteur de hosts SSH accordés à un user (spec 18 T3). */
function HostGrantsDialog({ login, onClose }: { login: string; onClose: () => void }) {
  const { t } = useTranslation()
  const hostsQuery = useSshHosts()
  const grantsQuery = useHostGrants(login)
  const ready = hostsQuery.data !== undefined && grantsQuery.data !== undefined

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('admin.users.hostGrantsTitle', { login })}</DialogTitle>
          <DialogDescription>{t('admin.users.hostGrantsHint')}</DialogDescription>
        </DialogHeader>
        {!ready ? (
          <p className="text-muted-foreground">…</p>
        ) : (
          <GrantsForm
            login={login}
            hosts={hostsQuery.data ?? []}
            initialChecked={grantsQuery.data?.hosts ?? []}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

export default function AdminUsers() {
  const { t } = useTranslation()
  const { listQuery } = useAdminUsers()
  const { data: users, isLoading, isError } = listQuery
  const [grantsFor, setGrantsFor] = useState<string | null>(null)

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold">{t('admin.users.title')}</h1>
      <p className="mb-6 text-sm text-muted-foreground">{t('admin.users.intro')}</p>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !users?.length && (
        <p className="text-muted-foreground">{t('admin.users.empty')}</p>
      )}

      {users && users.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                  {t('admin.users.login')}
                </th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                  {t('admin.users.name')}
                </th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                  {t('admin.users.instance')}
                </th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.login} className="border-b last:border-0">
                  <td className="px-4 py-2 font-medium">{u.login}</td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {u.display_name || '—'}
                    {u.email && <span className="ml-1 text-xs">({u.email})</span>}
                  </td>
                  <td className="px-4 py-2">
                    <InstanceSelect user={u} />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button size="sm" variant="ghost" onClick={() => setGrantsFor(u.login)}>
                      {t('admin.users.hostGrants')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {grantsFor && (
        <HostGrantsDialog login={grantsFor} onClose={() => setGrantsFor(null)} />
      )}
    </div>
  )
}
