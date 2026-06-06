import { useTranslation } from 'react-i18next'
import { useHosts } from './useHosts'

export default function AdminHosts() {
  const { t } = useTranslation()
  const { data: hosts, isLoading, isError } = useHosts()

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">{t('admin.hosts')}</h1>
      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !hosts?.length && (
        <p className="text-muted-foreground">{t('admin.hostsEmpty')}</p>
      )}
      {hosts && hosts.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.name')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.type')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.host')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.default')}</th>
              </tr>
            </thead>
            <tbody>
              {hosts.map((h) => (
                <tr key={h.name} className="border-b last:border-0">
                  <td className="px-4 py-2 font-medium">{h.name}</td>
                  <td className="px-4 py-2 text-muted-foreground">{h.type}</td>
                  <td className="px-4 py-2 text-muted-foreground font-mono text-xs">{h.docker_host ?? '—'}</td>
                  <td className="px-4 py-2">
                    {h.default ? (
                      <span className="text-green-600">✓</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
