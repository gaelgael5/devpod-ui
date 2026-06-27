# MCP Gateway — Lot 1 Frontend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un onglet « MCP » dans la page `/git-credentials` permettant à l'utilisateur d'enregistrer ses backends MCP, leurs clés de service (stockage local chiffré ou wallet, comme l'onglet Secrets), et d'émettre des apikeys clients donnant accès à un ensemble de services avec sélection de la clé par service.

**Architecture:** Feature React `features/mcp/` : un fichier `api.ts` (hooks TanStack Query mappant `/me/mcp/*` du backend lot 1), deux sous-composants (`MCPBackends` pour les services+clés, `MCPApikeys` pour les apikeys+grants), assemblés dans `MCPTab` monté comme 5e onglet de `CredentialsPage`. Réutilise les composants shadcn et le pattern storage de `SecretsTab`.

**Tech Stack:** Vite + React 18 + TypeScript strict, react-router-dom, TanStack Query, Tailwind + shadcn/ui, i18next, Vitest + React Testing Library + MSW.

**Dépendance :** ce plan consomme l'API du plan backend (`2026-06-22-mcp-gateway-backend.md`). Les endpoints doivent exister : `GET/POST/PATCH/DELETE /me/mcp/backends`, `GET/POST/DELETE /me/mcp/backends/{id}/keys`, `GET/POST /me/mcp/apikeys`, `POST /me/mcp/apikeys/{id}/revoke`, `DELETE /me/mcp/apikeys/{id}`, `GET/PUT /me/mcp/apikeys/{id}/grants`, `DELETE /me/mcp/apikeys/{id}/grants/{backend_id}`.

## Global Constraints

- TypeScript **strict** ; `erasableSyntaxOnly` actif → **pas de parameter properties** dans les constructeurs, pas d'enums const ; types via `interface`/`type` et `import type`.
- Conventions yoops : composants fonctionnels, hooks TanStack Query dans `api.ts`, libellés via `useTranslation()` (jamais de chaîne en dur visible).
- Tests : Vitest + React Testing Library ; `describe`/`it` (**jamais** `test`) ; rendu via `renderWithProviders` (`src/test/renderWithProviders.tsx`) ; mocks réseau via MSW (`src/test/handlers.ts`).
- i18n : toute clé ajoutée existe **dans `fr.json` ET `en.json`** (parité stricte).
- Réutiliser les composants shadcn existants (`@/components/ui/*`) ; ne pas réinventer Dialog/Select/Input/Button/Badge/Alert.
- Le token clair d'une apikey n'est affiché **qu'une seule fois** (à la création) et n'est jamais re-demandé.

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `frontend/src/features/mcp/api.ts` (créer) | Types DTO + hooks TanStack Query `/me/mcp/*` |
| `frontend/src/features/mcp/MCPBackends.tsx` (créer) | Liste des backends + dialogs création backend / clé |
| `frontend/src/features/mcp/MCPApikeys.tsx` (créer) | Liste apikeys + création (token one-time) + éditeur de grants |
| `frontend/src/features/mcp/MCPTab.tsx` (créer) | Assemble les deux sections |
| `frontend/src/features/git-credentials/CredentialsPage.tsx` (modif) | Ajout du 5e onglet « MCP » |
| `frontend/src/i18n/fr.json` (modif) | Clés `mcp.*` |
| `frontend/src/i18n/en.json` (modif) | Clés `mcp.*` |
| `frontend/src/test/handlers.ts` (modif) | Handlers MSW `/me/mcp/*` |
| `frontend/src/features/mcp/MCPBackends.test.tsx` (créer) | Test composant backends |
| `frontend/src/features/mcp/MCPApikeys.test.tsx` (créer) | Test composant apikeys (token one-time + grant) |

---

## Task 1 : api.ts — types et hooks

**Files:**
- Create: `frontend/src/features/mcp/api.ts`

**Interfaces:**
- Produces (types) : `MCPBackend`, `MCPBackendKey`, `MCPApikey`, `MCPGrant`, `BackendCreateBody`, `BackendUpdateBody`, `KeyCreateBody`, `GrantSetBody`, `CreatedApikey`.
- Produces (hooks) : `useBackends`, `useCreateBackend`, `useUpdateBackend`, `useDeleteBackend`, `useBackendKeys`, `useCreateKey`, `useDeleteKey`, `useApikeys`, `useCreateApikey`, `useRevokeApikey`, `useDeleteApikey`, `useGrants`, `useSetGrant`, `useDeleteGrant`.

- [ ] **Step 1 : Créer `frontend/src/features/mcp/api.ts`**

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type Transport = 'streamable_http' | 'sse' | 'stdio'
export type StorageType = 'local' | 'harpocrate'

export interface MCPBackend {
  id: string
  owner_login: string
  namespace: string
  name: string
  url: string
  transport: Transport
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface MCPBackendKey {
  id: string
  backend_id: string
  slug: string
  description: string
  storage_type: StorageType
  secret_value_vault_ref: string | null
  vault_identifier: string | null
  enabled: boolean
  created_at: string
}

export interface MCPApikey {
  id: string
  owner_login: string
  label: string
  revoked: boolean
  created_at: string
}

export interface MCPGrant {
  apikey_id: string
  backend_id: string
  backend_key_id: string
}

export interface BackendCreateBody {
  namespace: string
  name: string
  url: string
  transport: Transport
}

export interface BackendUpdateBody {
  name: string
  url: string
  transport: Transport
  enabled: boolean
}

export interface KeyCreateBody {
  slug: string
  description?: string
  storage_type: StorageType
  secret_value: string
  vault_identifier?: string | null
}

export interface GrantSetBody {
  backend_id: string
  backend_key_id: string
}

export interface CreatedApikey {
  id: string
  token: string
}

const QK = {
  backends: () => ['mcp', 'backends'] as const,
  keys: (backendId: string) => ['mcp', 'keys', backendId] as const,
  apikeys: () => ['mcp', 'apikeys'] as const,
  grants: (apikeyId: string) => ['mcp', 'grants', apikeyId] as const,
}

// ── Backends ──────────────────────────────────────────────────────────────────

export function useBackends() {
  return useQuery({
    queryKey: QK.backends(),
    queryFn: () => apiFetchJson<MCPBackend[]>('/me/mcp/backends'),
  })
}

export function useCreateBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BackendCreateBody) =>
      apiFetchJson<{ id: string }>('/me/mcp/backends', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.backends() }),
  })
}

export function useUpdateBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: BackendUpdateBody & { id: string }) =>
      apiFetchJson<{ id: string }>(`/me/mcp/backends/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.backends() }),
  })
}

export function useDeleteBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/me/mcp/backends/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.backends() }),
  })
}

// ── Clés de service ─────────────────────────────────────────────────────────────

export function useBackendKeys(backendId: string | null) {
  return useQuery({
    queryKey: QK.keys(backendId ?? ''),
    queryFn: () =>
      apiFetchJson<MCPBackendKey[]>(`/me/mcp/backends/${encodeURIComponent(backendId!)}/keys`),
    enabled: backendId !== null,
  })
}

export function useCreateKey(backendId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: KeyCreateBody) =>
      apiFetchJson<{ id: string }>(
        `/me/mcp/backends/${encodeURIComponent(backendId)}/keys`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.keys(backendId) }),
  })
}

export function useDeleteKey(backendId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      apiFetch(
        `/me/mcp/backends/${encodeURIComponent(backendId)}/keys/${encodeURIComponent(keyId)}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.keys(backendId) }),
  })
}

// ── Apikeys clients ─────────────────────────────────────────────────────────────

export function useApikeys() {
  return useQuery({
    queryKey: QK.apikeys(),
    queryFn: () => apiFetchJson<MCPApikey[]>('/me/mcp/apikeys'),
  })
}

export function useCreateApikey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { label: string }) =>
      apiFetchJson<CreatedApikey>('/me/mcp/apikeys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apikeys() }),
  })
}

export function useRevokeApikey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetchJson<{ id: string }>(`/me/mcp/apikeys/${encodeURIComponent(id)}/revoke`, {
        method: 'POST',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apikeys() }),
  })
}

export function useDeleteApikey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/me/mcp/apikeys/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apikeys() }),
  })
}

// ── Grants ────────────────────────────────────────────────────────────────────

export function useGrants(apikeyId: string | null) {
  return useQuery({
    queryKey: QK.grants(apikeyId ?? ''),
    queryFn: () =>
      apiFetchJson<MCPGrant[]>(`/me/mcp/apikeys/${encodeURIComponent(apikeyId!)}/grants`),
    enabled: apikeyId !== null,
  })
}

export function useSetGrant(apikeyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: GrantSetBody) =>
      apiFetchJson<{ apikey_id: string; backend_id: string }>(
        `/me/mcp/apikeys/${encodeURIComponent(apikeyId)}/grants`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.grants(apikeyId) }),
  })
}

export function useDeleteGrant(apikeyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (backendId: string) =>
      apiFetch(
        `/me/mcp/apikeys/${encodeURIComponent(apikeyId)}/grants/${encodeURIComponent(backendId)}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.grants(apikeyId) }),
  })
}
```

- [ ] **Step 2 : Vérifier la compilation TypeScript**

Run: `cd frontend && npx tsc --noEmit`
Expected: aucune erreur sur `api.ts`.

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/mcp/api.ts
git commit -m "feat(mcp-ui): hooks TanStack Query pour /me/mcp"
```

---

## Task 2 : i18n (fr + en)

**Files:**
- Modify: `frontend/src/i18n/fr.json`, `frontend/src/i18n/en.json`

**Interfaces:**
- Produces : namespace de clés `mcp.*` consommé par tous les composants des Tasks 3-5.

- [ ] **Step 1 : Ajouter le bloc `mcp` dans `fr.json`**

Insérer (avant la clé `"common"`, en respectant la virgule JSON) :

```json
  "mcp": {
    "tabLabel": "MCP",
    "title": "Passerelle MCP",
    "info": "Enregistrez vos serveurs MCP, leurs clés d'authentification, et émettez des apikeys clients pour connecter Claude web à un ensemble de services.",
    "backends": {
      "sectionTitle": "Serveurs MCP",
      "add": "Ajouter un serveur",
      "empty": "Aucun serveur MCP enregistré.",
      "dialogTitle": "Enregistrer un serveur MCP",
      "namespace": "Namespace (préfixe)",
      "namespaceHint": "minuscules, chiffres, underscore — sans « __ »",
      "name": "Nom",
      "url": "URL",
      "transport": "Transport",
      "keysTitle": "Clés d'authentification",
      "addKey": "Ajouter une clé",
      "noKeys": "Aucune clé.",
      "keyDialogTitle": "Ajouter une clé de service",
      "slug": "Slug fonctionnel",
      "slugHint": "ex : read, admin",
      "description": "Description",
      "storageType": "Stockage",
      "storageLocal": "Local (chiffré en base)",
      "storageHarpocrate": "Wallet Harpocrate",
      "wallet": "Wallet",
      "secretValue": "Valeur de la clé",
      "delete": "Supprimer",
      "confirmDelete": "Confirmer"
    },
    "apikeys": {
      "sectionTitle": "Apikeys clients",
      "add": "Émettre une apikey",
      "empty": "Aucune apikey émise.",
      "dialogTitle": "Émettre une apikey client",
      "label": "Libellé",
      "labelPlaceholder": "ex : Claude web — laptop",
      "tokenOnceTitle": "Apikey créée",
      "tokenOnceWarning": "Copiez cette valeur maintenant — elle ne sera plus affichée.",
      "revoked": "Révoquée",
      "revoke": "Révoquer",
      "delete": "Supprimer",
      "confirmDelete": "Confirmer",
      "grantsTitle": "Accès aux serveurs",
      "grantsHint": "Pour chaque serveur autorisé, choisissez la clé d'authentification à utiliser.",
      "noGrants": "Aucun accès configuré.",
      "selectKey": "Choisir une clé…",
      "addGrant": "Autoriser",
      "removeGrant": "Retirer"
    },
    "saving": "Enregistrement…",
    "save": "Enregistrer"
  },
```

- [ ] **Step 2 : Ajouter le bloc `mcp` équivalent dans `en.json`**

Insérer (même position) :

```json
  "mcp": {
    "tabLabel": "MCP",
    "title": "MCP Gateway",
    "info": "Register your MCP servers, their authentication keys, and issue client apikeys to connect Claude web to a set of services.",
    "backends": {
      "sectionTitle": "MCP Servers",
      "add": "Add a server",
      "empty": "No MCP server registered.",
      "dialogTitle": "Register an MCP server",
      "namespace": "Namespace (prefix)",
      "namespaceHint": "lowercase, digits, underscore — no \"__\"",
      "name": "Name",
      "url": "URL",
      "transport": "Transport",
      "keysTitle": "Authentication keys",
      "addKey": "Add a key",
      "noKeys": "No key.",
      "keyDialogTitle": "Add a service key",
      "slug": "Functional slug",
      "slugHint": "e.g. read, admin",
      "description": "Description",
      "storageType": "Storage",
      "storageLocal": "Local (encrypted in DB)",
      "storageHarpocrate": "Harpocrate wallet",
      "wallet": "Wallet",
      "secretValue": "Key value",
      "delete": "Delete",
      "confirmDelete": "Confirm"
    },
    "apikeys": {
      "sectionTitle": "Client apikeys",
      "add": "Issue an apikey",
      "empty": "No apikey issued.",
      "dialogTitle": "Issue a client apikey",
      "label": "Label",
      "labelPlaceholder": "e.g. Claude web — laptop",
      "tokenOnceTitle": "Apikey created",
      "tokenOnceWarning": "Copy this value now — it will not be shown again.",
      "revoked": "Revoked",
      "revoke": "Revoke",
      "delete": "Delete",
      "confirmDelete": "Confirm",
      "grantsTitle": "Server access",
      "grantsHint": "For each authorized server, choose the authentication key to use.",
      "noGrants": "No access configured.",
      "selectKey": "Choose a key…",
      "addGrant": "Authorize",
      "removeGrant": "Remove"
    },
    "saving": "Saving…",
    "save": "Save"
  },
```

- [ ] **Step 3 : Valider le JSON**

Run: `cd frontend && node -e "require('./src/i18n/fr.json'); require('./src/i18n/en.json'); console.log('json ok')"`
Expected: `json ok`.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(mcp-ui): clés i18n fr/en pour l'onglet MCP"
```

---

## Task 3 : Composant MCPBackends (serveurs + clés)

**Files:**
- Create: `frontend/src/features/mcp/MCPBackends.tsx`

**Interfaces:**
- Consumes: tous les hooks backend/key de `api.ts`, `useVaultKeys` (`@/features/vault/api`).
- Produces: `export default function MCPBackends()`.

- [ ] **Step 1 : Écrire `MCPBackends.tsx`**

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Server, Plus, Trash2, KeyRound } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useVaultKeys } from '@/features/vault/api'
import {
  useBackends,
  useCreateBackend,
  useDeleteBackend,
  useBackendKeys,
  useCreateKey,
  useDeleteKey,
  type StorageType,
  type Transport,
} from './api'

function AddBackendDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateBackend()
  const [namespace, setNamespace] = useState('')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [transport, setTransport] = useState<Transport>('streamable_http')

  function close() {
    setNamespace(''); setName(''); setUrl(''); setTransport('streamable_http')
    create.reset(); onClose()
  }

  function submit() {
    create.mutate(
      { namespace, name, url, transport },
      { onSuccess: close, onError: (e) => toast.error(e.message) },
    )
  }

  const canSubmit = !!namespace && !!name && !!url && !create.isPending

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('mcp.backends.dialogTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.namespace')}</Label>
            <Input value={namespace} onChange={(e) => setNamespace(e.target.value)} placeholder="rag" />
            <span className="text-xs text-muted-foreground">{t('mcp.backends.namespaceHint')}</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.name')}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.url')}</Label>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://rag.yoops.org/mcp" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.transport')}</Label>
            <Select value={transport} onValueChange={(v) => setTransport(v as Transport)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="streamable_http">streamable_http</SelectItem>
                <SelectItem value="sse">sse</SelectItem>
                <SelectItem value="stdio">stdio</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {create.error && (
            <Alert variant="destructive"><AlertDescription>{create.error.message}</AlertDescription></Alert>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {create.isPending ? t('mcp.saving') : t('mcp.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AddKeyDialog({ backendId, open, onClose }: { backendId: string; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const { data: vaultKeys = [] } = useVaultKeys()
  const create = useCreateKey(backendId)
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [storage, setStorage] = useState<StorageType>('local')
  const [vaultId, setVaultId] = useState('')
  const [value, setValue] = useState('')

  function close() {
    setSlug(''); setDescription(''); setStorage('local'); setVaultId(''); setValue('')
    create.reset(); onClose()
  }

  function submit() {
    create.mutate(
      {
        slug, description, storage_type: storage, secret_value: value,
        vault_identifier: storage === 'harpocrate' ? vaultId : null,
      },
      { onSuccess: close, onError: (e) => toast.error(e.message) },
    )
  }

  const canSubmit = !!slug && !!value && !create.isPending && (storage !== 'harpocrate' || !!vaultId)

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>{t('mcp.backends.keyDialogTitle')}</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.slug')}</Label>
            <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="read" />
            <span className="text-xs text-muted-foreground">{t('mcp.backends.slugHint')}</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.description')}</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.storageType')}</Label>
            <Select value={storage} onValueChange={(v) => setStorage(v as StorageType)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="local">{t('mcp.backends.storageLocal')}</SelectItem>
                <SelectItem value="harpocrate" disabled={vaultKeys.length === 0}>
                  {t('mcp.backends.storageHarpocrate')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          {storage === 'harpocrate' && (
            <div className="flex flex-col gap-1.5">
              <Label>{t('mcp.backends.wallet')}</Label>
              <Select value={vaultId} onValueChange={setVaultId}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {vaultKeys.map((k) => (
                    <SelectItem key={k.identifier} value={k.identifier}>{k.identifier}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label>{t('mcp.backends.secretValue')}</Label>
            <Input type="password" value={value} onChange={(e) => setValue(e.target.value)} />
          </div>
          {create.error && (
            <Alert variant="destructive"><AlertDescription>{create.error.message}</AlertDescription></Alert>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {create.isPending ? t('mcp.saving') : t('mcp.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function KeyList({ backendId }: { backendId: string }) {
  const { t } = useTranslation()
  const { data: keys = [] } = useBackendKeys(backendId)
  const del = useDeleteKey(backendId)
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="mt-2 flex flex-col gap-2 border-l pl-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase text-muted-foreground">{t('mcp.backends.keysTitle')}</span>
        <Button size="sm" variant="ghost" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-3.5 w-3.5" />{t('mcp.backends.addKey')}
        </Button>
      </div>
      {keys.length === 0 && <span className="text-xs text-muted-foreground">{t('mcp.backends.noKeys')}</span>}
      {keys.map((k) => (
        <div key={k.id} className="flex items-center gap-2 text-sm">
          <KeyRound className="h-3.5 w-3.5 text-muted-foreground" />
          <code className="font-mono">{k.slug}</code>
          <Badge variant="outline" className="text-xs">{k.storage_type}</Badge>
          <span className="text-muted-foreground">{k.description}</span>
          <Button size="sm" variant="ghost" className="ml-auto text-destructive"
            onClick={() => del.mutate(k.id, { onError: (e) => toast.error(e.message) })}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      ))}
      <AddKeyDialog backendId={backendId} open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}

export default function MCPBackends() {
  const { t } = useTranslation()
  const { data: backends = [], isLoading } = useBackends()
  const del = useDeleteBackend()
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('mcp.backends.sectionTitle')}</h2>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />{t('mcp.backends.add')}
        </Button>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && backends.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('mcp.backends.empty')}</p>
      )}
      {backends.map((b) => (
        <div key={b.id} className="rounded-lg border bg-card p-3">
          <div className="flex items-center gap-2">
            <Server className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium">{b.name}</span>
            <Badge variant="outline" className="font-mono text-xs">{b.namespace}</Badge>
            {!b.enabled && <Badge variant="secondary">disabled</Badge>}
            <span className="ml-2 text-xs text-muted-foreground">{b.url}</span>
            <Button size="sm" variant="ghost" className="ml-auto text-destructive"
              onClick={() => del.mutate(b.id, { onError: (e) => toast.error(e.message) })}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
          <KeyList backendId={b.id} />
        </div>
      ))}
      <AddBackendDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}
```

- [ ] **Step 2 : Vérifier la compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: aucune erreur.

> Vérification : confirmer que `sonner` (toast) et les composants `@/components/ui/{alert,badge,select}` existent (ils sont déjà importés par `SecretsTab.tsx` et d'autres features). Si `useVaultKeys` ne retourne pas d'objets `{ identifier }`, aligner sur sa signature réelle (confirmée : `identifier: string`).

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/mcp/MCPBackends.tsx
git commit -m "feat(mcp-ui): section serveurs MCP + clés de service"
```

---

## Task 4 : Composant MCPApikeys (apikeys + grants)

**Files:**
- Create: `frontend/src/features/mcp/MCPApikeys.tsx`

**Interfaces:**
- Consumes: hooks apikey/grant de `api.ts`, `useBackends`, `useBackendKeys`.
- Produces: `export default function MCPApikeys()`.

- [ ] **Step 1 : Écrire `MCPApikeys.tsx`**

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Key, Plus, Trash2, Copy, Check, Ban } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  useApikeys,
  useCreateApikey,
  useRevokeApikey,
  useDeleteApikey,
  useBackends,
  useBackendKeys,
  useGrants,
  useSetGrant,
  useDeleteGrant,
} from './api'

function CreateApikeyDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateApikey()
  const [label, setLabel] = useState('')
  const [token, setToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  function close() {
    setLabel(''); setToken(null); setCopied(false); create.reset(); onClose()
  }

  function submit() {
    create.mutate(
      { label },
      { onSuccess: (r) => setToken(r.token), onError: (e) => toast.error(e.message) },
    )
  }

  function copy() {
    if (token) {
      void navigator.clipboard.writeText(token)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{token ? t('mcp.apikeys.tokenOnceTitle') : t('mcp.apikeys.dialogTitle')}</DialogTitle>
        </DialogHeader>
        {token ? (
          <div className="flex flex-col gap-3">
            <Alert><AlertDescription>{t('mcp.apikeys.tokenOnceWarning')}</AlertDescription></Alert>
            <div className="flex items-center gap-1 rounded bg-muted/50 p-2">
              <code className="flex-1 break-all text-xs select-all">{token}</code>
              <Button size="sm" variant="ghost" onClick={copy}>
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={close}>{t('common.cancel')}</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label>{t('mcp.apikeys.label')}</Label>
              <Input value={label} onChange={(e) => setLabel(e.target.value)}
                placeholder={t('mcp.apikeys.labelPlaceholder')} />
            </div>
            {create.error && (
              <Alert variant="destructive"><AlertDescription>{create.error.message}</AlertDescription></Alert>
            )}
            <DialogFooter>
              <Button variant="ghost" onClick={close}>{t('common.cancel')}</Button>
              <Button onClick={submit} disabled={create.isPending}>
                {create.isPending ? t('mcp.saving') : t('mcp.save')}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

// Éditeur de grants : une ligne par serveur, avec un select de clé. C'est l'UX
// « accès à un ensemble de services avec sélection de la clé à utiliser ».
function GrantEditor({ apikeyId }: { apikeyId: string }) {
  const { t } = useTranslation()
  const { data: backends = [] } = useBackends()
  const { data: grants = [] } = useGrants(apikeyId)
  const setGrant = useSetGrant(apikeyId)
  const delGrant = useDeleteGrant(apikeyId)

  return (
    <div className="mt-2 flex flex-col gap-2 border-l pl-3">
      <span className="text-xs font-semibold uppercase text-muted-foreground">{t('mcp.apikeys.grantsTitle')}</span>
      <span className="text-xs text-muted-foreground">{t('mcp.apikeys.grantsHint')}</span>
      {backends.length === 0 && <span className="text-xs text-muted-foreground">{t('mcp.apikeys.noGrants')}</span>}
      {backends.map((b) => {
        const current = grants.find((g) => g.backend_id === b.id)
        return (
          <GrantRow
            key={b.id}
            backendId={b.id}
            backendName={b.name}
            namespace={b.namespace}
            currentKeyId={current?.backend_key_id ?? null}
            onSet={(keyId) => setGrant.mutate(
              { backend_id: b.id, backend_key_id: keyId },
              { onError: (e) => toast.error(e.message) },
            )}
            onRemove={() => delGrant.mutate(b.id, { onError: (e) => toast.error(e.message) })}
          />
        )
      })}
    </div>
  )
}

function GrantRow({
  backendId, backendName, namespace, currentKeyId, onSet, onRemove,
}: {
  backendId: string
  backendName: string
  namespace: string
  currentKeyId: string | null
  onSet: (keyId: string) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const { data: keys = [] } = useBackendKeys(backendId)

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="font-medium">{backendName}</span>
      <Badge variant="outline" className="font-mono text-xs">{namespace}</Badge>
      <Select value={currentKeyId ?? ''} onValueChange={onSet}>
        <SelectTrigger className="ml-auto h-8 w-44"><SelectValue placeholder={t('mcp.apikeys.selectKey')} /></SelectTrigger>
        <SelectContent>
          {keys.map((k) => (
            <SelectItem key={k.id} value={k.id}>{k.slug}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      {currentKeyId && (
        <Button size="sm" variant="ghost" className="text-destructive" onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  )
}

export default function MCPApikeys() {
  const { t } = useTranslation()
  const { data: apikeys = [], isLoading } = useApikeys()
  const revoke = useRevokeApikey()
  const del = useDeleteApikey()
  const [addOpen, setAddOpen] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium">{t('mcp.apikeys.sectionTitle')}</h2>
        <Button size="sm" onClick={() => setAddOpen(true)}>
          <Plus className="mr-1 h-4 w-4" />{t('mcp.apikeys.add')}
        </Button>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">{t('common.loading')}</p>}
      {!isLoading && apikeys.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('mcp.apikeys.empty')}</p>
      )}
      {apikeys.map((a) => (
        <div key={a.id} className="rounded-lg border bg-card p-3">
          <div className="flex items-center gap-2">
            <Key className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium">{a.label || a.id}</span>
            {a.revoked && <Badge variant="secondary">{t('mcp.apikeys.revoked')}</Badge>}
            {!a.revoked && (
              <Button size="sm" variant="ghost" className="ml-auto"
                onClick={() => revoke.mutate(a.id, { onError: (e) => toast.error(e.message) })}>
                <Ban className="mr-1 h-3.5 w-3.5" />{t('mcp.apikeys.revoke')}
              </Button>
            )}
            <Button size="sm" variant="ghost" className={a.revoked ? 'ml-auto text-destructive' : 'text-destructive'}
              onClick={() => del.mutate(a.id, { onError: (e) => toast.error(e.message) })}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
          {!a.revoked && <GrantEditor apikeyId={a.id} />}
        </div>
      ))}
      <CreateApikeyDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}
```

- [ ] **Step 2 : Vérifier la compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: aucune erreur.

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/features/mcp/MCPApikeys.tsx
git commit -m "feat(mcp-ui): section apikeys clients + éditeur de grants (token one-time)"
```

---

## Task 5 : MCPTab + onglet CredentialsPage + tests

**Files:**
- Create: `frontend/src/features/mcp/MCPTab.tsx`
- Modify: `frontend/src/features/git-credentials/CredentialsPage.tsx`
- Modify: `frontend/src/test/handlers.ts`
- Create: `frontend/src/features/mcp/MCPApikeys.test.tsx`

**Interfaces:**
- Consumes: `MCPBackends`, `MCPApikeys`.
- Produces: `export default function MCPTab()` ; onglet « MCP » visible dans `/git-credentials`.

- [ ] **Step 1 : Créer `MCPTab.tsx`**

```tsx
import { useTranslation } from 'react-i18next'
import { Network } from 'lucide-react'
import MCPBackends from './MCPBackends'
import MCPApikeys from './MCPApikeys'

export default function MCPTab() {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border bg-muted/40 p-5">
        <div className="mb-2 flex items-center gap-2">
          <Network className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{t('mcp.title')}</span>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">{t('mcp.info')}</p>
      </div>
      <MCPBackends />
      <MCPApikeys />
    </div>
  )
}
```

- [ ] **Step 2 : Ajouter l'onglet dans `CredentialsPage.tsx`**

Modifier `frontend/src/features/git-credentials/CredentialsPage.tsx` :

```tsx
import { useTranslation } from 'react-i18next'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import GitCredentialManager from './GitCredentialManager'
import VaultTab from '@/features/vault/VaultTab'
import CertificatesTab from '@/features/certificates/CertificatesTab'
import SecretsTab from '@/features/secrets/SecretsTab'
import MCPTab from '@/features/mcp/MCPTab'

export default function CredentialsPage() {
  const { t } = useTranslation()
  return (
    <Tabs defaultValue="vault" className="flex flex-col gap-4">
      <TabsList className="self-start">
        <TabsTrigger value="vault">{t('vault.tabLabel')}</TabsTrigger>
        <TabsTrigger value="certificates">{t('certificates.tabLabel')}</TabsTrigger>
        <TabsTrigger value="secrets">{t('secrets.tabLabel')}</TabsTrigger>
        <TabsTrigger value="git">{t('gitCredentials.title')}</TabsTrigger>
        <TabsTrigger value="mcp">{t('mcp.tabLabel')}</TabsTrigger>
      </TabsList>
      <TabsContent value="vault" className="mt-0"><VaultTab /></TabsContent>
      <TabsContent value="certificates" className="mt-0"><CertificatesTab /></TabsContent>
      <TabsContent value="secrets" className="mt-0"><SecretsTab /></TabsContent>
      <TabsContent value="git" className="mt-0"><GitCredentialManager /></TabsContent>
      <TabsContent value="mcp" className="mt-0"><MCPTab /></TabsContent>
    </Tabs>
  )
}
```

- [ ] **Step 3 : Ajouter les handlers MSW**

Dans `frontend/src/test/handlers.ts`, ajouter aux handlers existants (importer `http, HttpResponse` déjà présents) :

```typescript
  http.get('/me/mcp/backends', () => HttpResponse.json([])),
  http.post('/me/mcp/backends', () => HttpResponse.json({ id: 'b-new' }, { status: 201 })),
  http.delete('/me/mcp/backends/:id', () => new HttpResponse(null, { status: 204 })),
  http.get('/me/mcp/backends/:id/keys', () => HttpResponse.json([])),
  http.post('/me/mcp/backends/:id/keys', () => HttpResponse.json({ id: 'k-new' }, { status: 201 })),
  http.delete('/me/mcp/backends/:id/keys/:keyId', () => new HttpResponse(null, { status: 204 })),
  http.get('/me/mcp/apikeys', () => HttpResponse.json([])),
  http.post('/me/mcp/apikeys', () => HttpResponse.json({ id: 'a-new', token: 'mcpk_abc123' }, { status: 201 })),
  http.post('/me/mcp/apikeys/:id/revoke', () => HttpResponse.json({ id: 'a-new' })),
  http.delete('/me/mcp/apikeys/:id', () => new HttpResponse(null, { status: 204 })),
  http.get('/me/mcp/apikeys/:id/grants', () => HttpResponse.json([])),
  http.put('/me/mcp/apikeys/:id/grants', () => HttpResponse.json({ apikey_id: 'a-new', backend_id: 'b1' })),
  http.delete('/me/mcp/apikeys/:id/grants/:backendId', () => new HttpResponse(null, { status: 204 })),
```

Et ajouter le handler du wallet (consommé par `useVaultKeys` au rendu de `MCPBackends`), absent du fichier — endpoint réel `/vault/keys` :

```typescript
  http.get('/vault/keys', () => HttpResponse.json([])),
```

> Confirmé : `src/test/handlers.ts` exporte `export const handlers = [...]` et `src/test/server.ts` exporte `export const server = setupServer(...handlers)`.

- [ ] **Step 4 : Écrire le test du flux apikey (création + token one-time)**

Créer `frontend/src/features/mcp/MCPApikeys.test.tsx` :

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { renderWithProviders } from '@/test/renderWithProviders'
import MCPApikeys from './MCPApikeys'

describe('MCPApikeys', () => {
  it("affiche l'état vide quand aucune apikey", async () => {
    renderWithProviders(<MCPApikeys />)
    expect(await screen.findByText(/Aucune apikey/i)).toBeInTheDocument()
  })

  it('crée une apikey et affiche le token clair une seule fois', async () => {
    const { server } = await import('@/test/server')
    server.use(
      http.get('/me/mcp/apikeys', () => HttpResponse.json([])),
      http.post('/me/mcp/apikeys', () =>
        HttpResponse.json({ id: 'a1', token: 'mcpk_secret_once' }, { status: 201 })),
    )
    const user = userEvent.setup()
    renderWithProviders(<MCPApikeys />)

    await user.click(await screen.findByRole('button', { name: /Émettre une apikey/i }))
    await user.click(await screen.findByRole('button', { name: /Enregistrer/i }))

    await waitFor(() => expect(screen.getByText('mcpk_secret_once')).toBeInTheDocument())
    expect(screen.getByText(/ne sera plus affichée/i)).toBeInTheDocument()
  })
})
```

> Confirmé : le projet importe le serveur MSW dynamiquement dans le test — `const { server } = await import('@/test/server')` (cf. `AdminProfileSources.test.tsx`).

- [ ] **Step 5 : Lancer les tests + compilation + lint**

Run:
```bash
cd frontend && npx tsc --noEmit && npx vitest run src/features/mcp/ && npm run lint
```
Expected: compilation OK, tests verts, lint OK.

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/features/mcp/MCPTab.tsx frontend/src/features/git-credentials/CredentialsPage.tsx frontend/src/test/handlers.ts frontend/src/features/mcp/MCPApikeys.test.tsx
git commit -m "feat(mcp-ui): onglet MCP dans CredentialsPage + handlers MSW + tests"
```

---

## Self-Review

**1. Couverture (lot 1 frontend) :**
- Onglet MCP dans `/git-credentials` → Task 5 (5e `TabsTrigger`) ✓
- Enregistrement backends + liste + suppression → Task 3 ✓
- Clés de service avec storage local/wallet (sélecteur wallet désactivé si aucun) → Task 3 (réutilise pattern SecretsTab + `useVaultKeys`) ✓
- Apikeys clients, token affiché une seule fois → Task 4 (`CreateApikeyDialog`, état `token`) ✓
- Accès à un ensemble de services avec sélection de la clé → Task 4 (`GrantEditor`/`GrantRow`, un select de clé par backend) ✓
- Révocation + suppression apikey → Task 4 ✓
- i18n fr/en en parité → Task 2 ✓

**2. Placeholders :** aucun « TBD/TODO ». Trois notes « vérification » pointent vers des fichiers réels (`sonner`/ui components, tableau handlers + `/me/vault/keys`, `@/test/server`) à confirmer, pas des trous de contenu.

**3. Cohérence des types :** les noms de hooks (`useBackends`, `useCreateKey`, `useSetGrant`…) et de types (`MCPBackend`, `KeyCreateBody`, `GrantSetBody`, `CreatedApikey`) sont identiques entre `api.ts` (Task 1) et les composants (Tasks 3-4). Les champs DTO (`namespace`, `slug`, `storage_type`, `backend_key_id`, `token`) correspondent aux réponses du plan backend. Clé i18n `mcp.*` définie en Task 2 avant tout usage.

**Dépendance d'exécution :** ce plan ne passe au vert (tests d'intégration réels) qu'une fois le backend du plan `2026-06-22-mcp-gateway-backend.md` déployé. Les tests Vitest, eux, mockent l'API via MSW et sont autonomes.
