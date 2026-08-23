import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
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
import { Badge } from '@/components/ui/badge'
import { useTermixInstances } from './useTermixInstances'
import {
  MAX_TERMIX_INSTANCES,
  useAdminUsers,
  useHostGrants,
  useSetHostGrants,
  useSshHosts,
  type AdminUser,
  type SshHost,
} from './useAdminUsers'

// Radix interdit une valeur vide sur SelectItem : sentinelle pour l'ajout.
const ADD = '__add__'

/** Multi-sélection d'instances Termix pour un user (jusqu'à 3, spec 18 T4b).
 *  Badges retirables + un Select d'ajout filtré, désactivé au plafond. */
function InstancePicker({ user }: { user: AdminUser }) {
  const { t } = useTranslation()
  const { listQuery } = useTermixInstances()
  const { setInstances } = useAdminUsers()
  const instances = listQuery.data ?? []
  const selected = user.termix_instance_ids
  const nameOf = (id: string) => instances.find((i) => i.id === id)?.name ?? id
  const available = instances.filter((i) => !selected.includes(i.id))
  const atCap = selected.length >= MAX_TERMIX_INSTANCES
  // Le PUT est SYNCHRONE (attend la fin du provisioning Termix) : tant qu'il tourne on
  // désactive tout + spinner → pas de clic concurrent, plus de course (spec 18).
  const busy = setInstances.isPending

  function update(ids: string[]) {
    setInstances.mutate({ login: user.login, instanceIds: ids })
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {selected.length === 0 && !busy && (
        <span className="text-xs text-muted-foreground">{t('admin.users.inheritDefault')}</span>
      )}
      {selected.map((id) => (
        <Badge key={id} variant="secondary" className="gap-1">
          {nameOf(id)}
          <button
            type="button"
            aria-label={t('admin.users.remove', { name: nameOf(id) })}
            className="ml-0.5 text-muted-foreground hover:text-foreground disabled:opacity-40"
            disabled={busy}
            onClick={() => update(selected.filter((x) => x !== id))}
          >
            ×
          </button>
        </Badge>
      ))}
      {busy ? (
        <Loader2
          className="h-3.5 w-3.5 animate-spin text-muted-foreground"
          aria-label={t('admin.users.provisioning')}
        />
      ) : (
        !atCap &&
        available.length > 0 && (
          <Select value={ADD} onValueChange={(v) => v !== ADD && update([...selected, v])}>
            <SelectTrigger className="h-7 w-auto gap-1 text-xs">
              <SelectValue placeholder={t('admin.users.addInstance')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ADD} disabled>
                {t('admin.users.addInstance')}
              </SelectItem>
              {available.map((i) => (
                <SelectItem key={i.id} value={i.id}>
                  {i.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )
      )}
    </div>
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
                    <InstancePicker user={u} />
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
