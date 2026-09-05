// Liste des types d'hyperviseurs. La création et l'édition vivent sur leur
// propre page (`AdminHypervisorTypeEditor`) : le formulaire porte des éditeurs
// de scripts, des actions et des variables, qu'une popup scrollable ne peut pas
// présenter — et dont la saisie disparaissait à la moindre fermeture.

import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useAdminHypervisorTypes } from './useAdminHypervisorTypes'

export default function AdminHypervisorTypes() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { typesQuery, deleteType } = useAdminHypervisorTypes()
  const { data: types, isLoading, isError } = typesQuery

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t('admin.hypervisorTypes')}</h1>
        <Button size="sm" onClick={() => navigate('/admin/hypervisor-types/new')}>
          {t('admin.addHypervisorType')}
        </Button>
      </div>

      {isLoading && <p className="text-muted-foreground">…</p>}
      {isError && <p className="text-sm text-destructive">{t('errors.loadFailed')}</p>}
      {!isLoading && !isError && !types?.length && (
        <p className="text-muted-foreground">{t('admin.hypervisorTypesEmpty')}</p>
      )}
      {types && types.length > 0 && (
        <div className="rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.form.hypervisorLabel')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.col.name')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.form.addScript')}</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('admin.form.destroyScript')}</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {types.map((ht) => (
                <tr key={ht.name} className="border-b last:border-0">
                  <td className="px-4 py-2 font-medium">{ht.label || '—'}</td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{ht.name}</td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground truncate max-w-xs">{ht.add_script || '—'}</td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground truncate max-w-xs">{ht.destroy_script || '—'}</td>
                  <td className="px-4 py-2 text-right flex items-center justify-end gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigate(`/admin/hypervisor-types/${ht.name}`)}
                    >
                      {t('workspaces.actions.edit')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => deleteType.mutate(ht.name)}
                      disabled={deleteType.isPending}
                    >
                      {t('workspaces.actions.delete')}
                    </Button>
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
