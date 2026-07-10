import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useUserStore } from '@/store/user'
import { useCreateSession } from '@/features/workspaces/useWorkspaceSessions'
import SessionTerminalWindow from './SessionTerminalWindow'
import { useCloseSession, useSessions, type SessionEntry } from './useSessions'

type Filter = 'all' | SessionEntry['family']

/** Nom de workspace (sans le préfixe `{owner}-`) pour construire l'URL WS `/me/...`. */
function wsNameOf(e: SessionEntry): string {
  if (e.family === 'test') return e.workspace ?? ''
  const prefix = `${e.owner}-`
  return e.target.startsWith(prefix) ? e.target.slice(prefix.length) : e.target
}

/** Un admin peut agir sur le conteneur/VM d'un autre user ; sinon seulement le sien. */
function owns(e: SessionEntry, login: string, isAdmin: boolean): boolean {
  return e.owner === login || isAdmin
}

function canOpen(e: SessionEntry, login: string, isAdmin: boolean): boolean {
  if (e.family === 'host') return isAdmin
  if (e.unreachable) return false
  if (e.family === 'workspace') return owns(e, login, isAdmin) && !!e.session
  return owns(e, login, isAdmin) // test
}

/** Fermeture possible : host/test seulement si attaché (rien à détacher sinon). */
function canClose(e: SessionEntry, login: string, isAdmin: boolean): boolean {
  if (e.family === 'workspace') return owns(e, login, isAdmin) && !!e.session
  if (e.family === 'host') return isAdmin && e.attached
  return owns(e, login, isAdmin) && e.attached // test
}

function openUrl(e: SessionEntry, login: string): string {
  if (e.family === 'host') return `/admin/hosts/${encodeURIComponent(e.target)}/ssh`
  const name = wsNameOf(e)
  // Vue admin sur le conteneur d'un autre : le backend résout le ws_id sur ?owner=.
  const ownerParam = e.owner !== login ? `&owner=${encodeURIComponent(e.owner)}` : ''
  if (e.family === 'test') {
    return `/me/workspaces/${encodeURIComponent(name)}/ssh?ssh_test=${encodeURIComponent(e.target)}${ownerParam}`
  }
  return `/me/workspaces/${encodeURIComponent(name)}/ssh?session=${encodeURIComponent(e.session ?? 'main')}${ownerParam}`
}

export default function SessionsView() {
  const { t } = useTranslation()
  const login = useUserStore((s) => s.user?.login ?? '')
  const isAdmin = useUserStore((s) => s.isAdmin())
  const { data, isLoading, isError, refetch } = useSessions()
  const createSession = useCreateSession()
  const closeSession = useCloseSession()

  const [filter, setFilter] = useState<Filter>('all')
  const [term, setTerm] = useState<{ wsUrl: string; title: string } | null>(null)
  const [newWs, setNewWs] = useState('')
  const [newName, setNewName] = useState('')

  const entries = data ?? []
  const shown = filter === 'all' ? entries : entries.filter((e) => e.family === filter)

  // Workspaces que l'utilisateur possède (pour créer une nouvelle session).
  const ownWorkspaces = useMemo(() => {
    const names = new Set<string>()
    for (const e of data ?? []) {
      if (e.family === 'workspace' && e.owner === login) names.add(wsNameOf(e))
    }
    return [...names].sort()
  }, [data, login])

  function open(e: SessionEntry) {
    const family = t(`sessions.family.${e.family}`)
    const label = e.session ? `${wsNameOf(e)} · ${e.session}` : e.target
    setTerm({ wsUrl: openUrl(e, login), title: `${family} — ${label}` })
  }

  function close(e: SessionEntry) {
    closeSession.mutate(
      { family: e.family, target: e.target, owner: e.owner, session: e.session },
      {
        onSuccess: () => {
          toast.success(t('sessions.closed', { name: e.session ?? e.target }))
          refetch()
        },
        onError: (err: Error) => toast.error(err.message),
      },
    )
  }

  function createAndOpen() {
    const ws = newWs || ownWorkspaces[0]
    if (!ws || !newName.trim()) return
    createSession.mutate(
      { wsName: ws, name: newName.trim() },
      {
        onSuccess: () => {
          toast.success(t('sessions.created', { name: newName.trim() }))
          setTerm({
            wsUrl: `/me/workspaces/${encodeURIComponent(ws)}/ssh?session=${encodeURIComponent(newName.trim())}`,
            title: `${t('sessions.family.workspace')} — ${ws} · ${newName.trim()}`,
          })
          setNewName('')
          refetch()
        },
        onError: (err: Error) => toast.error(err.message),
      },
    )
  }

  const filters: Filter[] = isAdmin ? ['all', 'workspace', 'host', 'test'] : ['all', 'workspace', 'test']

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-2 text-2xl font-semibold">{t('sessions.title')}</h1>
      <p className="mb-5 text-sm text-muted-foreground">{t('sessions.intro')}</p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {filters.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full border px-3 py-1 text-sm ${
              filter === f ? 'border-foreground bg-muted font-medium' : 'text-muted-foreground'
            }`}
          >
            {t(`sessions.filter.${f}`)}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">
          {t('sessions.count', { n: entries.length })}
        </span>
      </div>

      {/* Nouvelle session */}
      <div className="mb-5 flex flex-wrap items-end gap-2 rounded-md border bg-muted/40 p-3">
        <select
          value={newWs || ownWorkspaces[0] || ''}
          onChange={(e) => setNewWs(e.target.value)}
          disabled={ownWorkspaces.length === 0}
          className="h-9 rounded-md border bg-background px-2 text-sm"
        >
          {ownWorkspaces.length === 0 && <option value="">{t('sessions.noWorkspace')}</option>}
          {ownWorkspaces.map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder={t('sessions.newNamePlaceholder')}
          className="h-9 w-40"
        />
        <Button
          onClick={createAndOpen}
          disabled={ownWorkspaces.length === 0 || !newName.trim() || createSession.isPending}
        >
          {createSession.isPending ? '…' : t('sessions.newSession')}
        </Button>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}

      {data && shown.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('sessions.empty')}</p>
      )}

      {data && shown.length > 0 && (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/60 text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="px-3 py-2">{t('sessions.col.kind')}</th>
                <th className="px-3 py-2">{t('sessions.col.target')}</th>
                <th className="px-3 py-2">{t('sessions.col.session')}</th>
                {isAdmin && <th className="px-3 py-2">{t('sessions.col.owner')}</th>}
                <th className="px-3 py-2">{t('sessions.col.state')}</th>
                <th className="px-3 py-2 text-right">{t('sessions.col.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((e, i) => (
                <tr key={`${e.family}-${e.target}-${e.session ?? ''}-${i}`} className="border-t">
                  <td className="px-3 py-2 font-mono text-xs">{t(`sessions.family.${e.family}`)}</td>
                  <td className="px-3 py-2 font-mono text-xs">{e.target}</td>
                  <td className="px-3 py-2 font-mono text-xs">{e.session ?? '—'}</td>
                  {isAdmin && <td className="px-3 py-2">{e.owner}</td>}
                  <td className="px-3 py-2">
                    {e.unreachable && (
                      <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                        {t('sessions.unreachable')}
                      </span>
                    )}
                    {e.attached && (
                      <span className="rounded bg-green-100 px-2 py-0.5 text-xs text-green-800">
                        {t('sessions.attached')}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!canOpen(e, login, isAdmin)}
                        onClick={() => open(e)}
                      >
                        {t('sessions.open')}
                      </Button>
                      {canClose(e, login, isAdmin) && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={closeSession.isPending}
                          onClick={() => close(e)}
                        >
                          {t('sessions.close')}
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {term && (
        <SessionTerminalWindow wsUrl={term.wsUrl} title={term.title} onClose={() => setTerm(null)} />
      )}
    </div>
  )
}
