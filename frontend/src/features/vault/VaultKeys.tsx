import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAddVaultKey, useDeleteVaultKey, useTestVaultKey, useVaultKeys } from './api'

export default function VaultKeys() {
  const { data: keys = [], isLoading } = useVaultKeys()
  const addKey = useAddVaultKey()
  const deleteKey = useDeleteVaultKey()
  const testKey = useTestVaultKey()
  const [form, setForm] = useState({
    identifier: '',
    token: '',
    url: 'https://vault.yoops.org',
    description: '',
  })
  const [testResults, setTestResults] = useState<Record<string, string>>({})

  const handleAdd = () => {
    addKey.mutate(form, {
      onSuccess: () =>
        setForm({ identifier: '', token: '', url: 'https://vault.yoops.org', description: '' }),
    })
  }

  const handleTest = (id: string) => {
    testKey.mutate(id, {
      onSuccess: (r) =>
        setTestResults((p) => ({ ...p, [id]: `wallet: ${r.wallet_id.slice(0, 8)}…` })),
      onError: () => setTestResults((p) => ({ ...p, [id]: 'échec' })),
    })
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <h1 className="text-2xl font-bold">Clés Harpocrate</h1>

      <Card>
        <CardHeader>
          <CardTitle>Ajouter une clé</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Identifiant</Label>
              <Input
                placeholder="api1"
                value={form.identifier}
                onChange={(e) => setForm({ ...form, identifier: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label>URL</Label>
              <Input
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label>Token hrpv_*</Label>
            <Input
              type="password"
              placeholder="hrpv_1_…"
              value={form.token}
              onChange={(e) => setForm({ ...form, token: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <Label>Description</Label>
            <Input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          <Button
            onClick={handleAdd}
            disabled={addKey.isPending || !form.identifier || !form.token}
          >
            Ajouter
          </Button>
        </CardContent>
      </Card>

      {isLoading && <p className="text-muted-foreground">Chargement…</p>}

      {keys.map((key) => (
        <Card key={key.identifier}>
          <CardContent className="flex items-center gap-3 pt-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-mono font-semibold">{key.identifier}</span>
                {testResults[key.identifier] && (
                  <Badge variant="secondary" className="text-xs">
                    {testResults[key.identifier]}
                  </Badge>
                )}
              </div>
              <p className="text-muted-foreground truncate text-sm">{key.url}</p>
              {key.description && <p className="text-sm">{key.description}</p>}
            </div>
            <Button variant="ghost" size="sm" onClick={() => handleTest(key.identifier)}>
              Tester
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => deleteKey.mutate(key.identifier)}
              className="text-destructive"
            >
              Supprimer
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
