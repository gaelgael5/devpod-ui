# Galerie Docker Compose — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** UI complète de la galerie docker-compose, visible et utilisable dans l'app : un admin gère les templates (galerie + éditeur) ; un dev parcourt la galerie, instancie une stack sur un nœud `ssh` et pilote ses déploiements (statut, logs, start/stop/restart/down).

**Architecture:** Feature React `frontend/src/features/compose/` (api client + hooks TanStack Query + pages + composants), consommant l'API backend `/api/compose/*` déjà livrée. Deux prérequis backend (read RBAC + endpoint nodes) pour débloquer le flux dev. Patterns calqués sur `features/profiles` et `features/mcp`.

**Tech Stack:** React 19, Vite, TS strict, TanStack Query, Zustand, shadcn/ui, react-router v7, i18next, lucide-react, Prism (éditeur YAML), Vitest + RTL + MSW.

## Global Constraints

- **API réelle backend** (préfixe `/api/compose`, via `apiFetchJson`/`apiFetch` de `shared/api/client.ts`) :
  - Templates : `GET /api/compose/templates?tag=`, `GET /api/compose/templates/{id}`, `POST /api/compose/templates`→`{template,warnings}`, `PUT /api/compose/templates/{id}`→`{template,warnings}`, `DELETE /api/compose/templates/{id}`(204).
  - Déploiements : `GET /api/compose/deployments`, `POST /api/compose/deployments` body `{template_id,node_id,name,env_values}` → deployment (409 `detail:{error:"port_conflict",conflicts:[],suggestion}`), `POST /api/compose/deployments/{id}/{action}` (action∈stop|start|restart), `DELETE /api/compose/deployments/{id}`(204), `GET /api/compose/deployments/{id}/logs?service=&tail=`→`{output}`, `GET /api/compose/deployments/{id}/status`→`{deployment_id,status}`.
  - Nodes : `GET /api/compose/nodes`→`[{node_id,name}]` (ajouté en Task BE1).
- **RBAC UI** : galerie+déploiements = user (`/compose`, route sous AppShell) ; gestion templates = admin (`/admin/compose`, sous `AdminGuard`).
- **Secrets** : un paramètre `type=secret` se saisit comme **référence** `${vault://...}` (jamais une valeur en clair) ; le champ est un texte de référence.
- **Modèles** (DTO backend) : `ComposeParam {key,label,description?,type,default?,required,options?,secret_ref_hint?}` avec `type ∈ string|number|bool|enum|port|secret` ; `ComposeTemplate {id,name,description,tags[],version,compose_content,parameters[],source,created_at?,updated_at?}` ; `ComposeDeployment {id,template_id,template_version,node_id,owner_login,env_values,host_ports[],status,last_error?,created_at?,updated_at?}` avec `status ∈ created|running|partial|stopped|error`.
- Conventions : `apiFetchJson<T>`/`apiFetch` ; hooks `useQuery`/`useMutation` avec `queryKey` constant + invalidation ; erreurs mutation → `toast.error(err.message)` (le client met le `detail` FastAPI dans `err.message`) ; formulaires `useState` + validation inline (pas de react-hook-form) ; i18n `useTranslation()` + clés dans `en.json` ET `fr.json` ; TS strict, **pas de `any`** ; fichiers ≤ 300 lignes.
- Tests : Vitest (`npm test` = `vitest run --maxWorkers=1`), RTL, MSW (`src/test/handlers.ts`, `renderWithProviders`, `useUserStore.setState`). `npx tsc --noEmit` + lint doivent rester verts.
- Commits conventionnels FR, branche `dev`.

---

# LOT BE — Prérequis backend (débloquer le flux dev)

### Task BE1: RBAC lecture templates + endpoint nodes

**Files:**
- Modify: `backend/src/portal/routes/compose.py`
- Test: `backend/tests/compose/test_routes_nodes.py`

**Interfaces:**
- Produces : `GET /api/compose/nodes` (require_user) → `list[{node_id,name}]` (hosts `type=="ssh"`). `GET /api/compose/templates` + `GET /api/compose/templates/{id}` passent de `require_admin` à `require_user` (lecture galerie pour devs). POST/PUT/DELETE templates **restent** `require_admin`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/compose/test_routes_nodes.py
from types import SimpleNamespace
from portal.routes import compose as r


def test_eligible_nodes_filters_ssh() -> None:
    hosts = [
        SimpleNamespace(name="n1", type="ssh"),
        SimpleNamespace(name="tls", type="docker-tls"),
        SimpleNamespace(name="n2", type="ssh"),
    ]
    rows = r._eligible_nodes(hosts)
    assert rows == [{"node_id": "n1", "name": "n1"}, {"node_id": "n2", "name": "n2"}]
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/compose/test_routes_nodes.py -v` → FAIL (`_eligible_nodes` absent).

- [ ] **Step 3: Implement**

Dans `routes/compose.py` :
1. Changer le dependency des deux routes GET templates (`list_templates`, `get_template`) de `Depends(require_admin)` à `Depends(require_user)`. Laisser POST/PUT/DELETE sur `require_admin`. (`require_user` est déjà importé pour les déploiements.)
2. Ajouter le helper + la route nodes :
```python
from ..config.store import load_global


def _eligible_nodes(hosts: list) -> list[dict[str, str]]:
    return [{"node_id": h.name, "name": h.name} for h in hosts if h.type == "ssh"]


@router.get("/nodes")
async def list_nodes(
    user: Annotated[UserInfo, Depends(require_user)],
) -> list[dict[str, str]]:
    return _eligible_nodes(load_global().hosts)
```

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/compose/test_routes_nodes.py -v` → PASS.

- [ ] **Step 5: Lint + type + suite**

`cd backend && uv run ruff check src/portal/routes/compose.py tests/compose/ && uv run mypy src/portal/routes/compose.py && uv run pytest tests/compose/ -q` → vert.

- [ ] **Step 6: Commit**

```bash
git add backend/src/portal/routes/compose.py backend/tests/compose/test_routes_nodes.py
git commit -m "feat(compose-gallery): GET templates en lecture user + GET /nodes (flux dev)"
```

---

# LOT FE — Frontend

### Task FE1: Types + client API

**Files:**
- Create: `frontend/src/features/compose/api/types.ts`, `frontend/src/features/compose/api/compose.ts`
- Test: `frontend/src/features/compose/api/compose.test.ts`

**Interfaces:**
- Produces (types) : `ComposeParamType`, `ComposeParam`, `TemplateSource`, `ComposeTemplate`, `DeploymentStatus`, `ComposeDeployment`, `NodeRef`, `TemplateBody`, `DeploymentCreateBody`, `PortConflictDetail`, `TemplateSaveResult`.
- Produces (client) : `listTemplates(tag?)`, `getTemplate(id)`, `createTemplate(body)`, `updateTemplate(id,body)`, `deleteTemplate(id)`, `listNodes()`, `listDeployments()`, `createDeployment(body)`, `deploymentAction(id,action)`, `deleteDeployment(id)`, `deploymentLogs(id,opts)`, `deploymentStatus(id)`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/compose/api/compose.test.ts
import { describe, it, expect } from 'vitest'
import type { ComposeTemplate, ComposeDeployment } from './types'

describe('compose types', () => {
  it('template shape compiles', () => {
    const t: ComposeTemplate = {
      id: 'browserless', name: 'B', description: '', tags: ['web'], version: '1',
      compose_content: 'services: {}', parameters: [], source: 'user',
    }
    expect(t.id).toBe('browserless')
  })
  it('deployment status union', () => {
    const d: ComposeDeployment = {
      id: 'd1', template_id: 't', template_version: '1', node_id: 'n',
      owner_login: 'alice', env_values: {}, host_ports: [], status: 'running',
    }
    expect(d.status).toBe('running')
  })
})
```

- [ ] **Step 2: Run** `cd frontend && npm test -- src/features/compose/api/compose.test.ts` → FAIL (types module absent).

- [ ] **Step 3: Write types.ts**

```ts
// frontend/src/features/compose/api/types.ts
export type ComposeParamType = 'string' | 'number' | 'bool' | 'enum' | 'port' | 'secret'
export type TemplateSource = 'user' | 'builtin' | 'imported'
export type DeploymentStatus = 'created' | 'running' | 'partial' | 'stopped' | 'error'

export interface ComposeParam {
  key: string
  label: string
  description?: string | null
  type: ComposeParamType
  default?: string | null
  required: boolean
  options?: string[] | null
  secret_ref_hint?: string | null
}

export interface ComposeTemplate {
  id: string
  name: string
  description: string
  tags: string[]
  version: string
  compose_content: string
  parameters: ComposeParam[]
  source: TemplateSource
  created_at?: string | null
  updated_at?: string | null
}

export interface ComposeDeployment {
  id: string
  template_id: string
  template_version: string
  node_id: string
  owner_login: string
  env_values: Record<string, string>
  host_ports: number[]
  status: DeploymentStatus
  last_error?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface NodeRef {
  node_id: string
  name: string
}

export interface TemplateBody {
  name: string
  description: string
  tags: string[]
  version: string
  compose_content: string
  parameters: ComposeParam[]
  source: TemplateSource
}

export interface DeploymentCreateBody {
  template_id: string
  node_id: string
  name: string
  env_values: Record<string, string>
}

export interface TemplateSaveResult {
  template: ComposeTemplate
  warnings: string[]
}

export interface PortConflictDetail {
  error: string
  conflicts: number[]
  suggestion: number | null
}
```

- [ ] **Step 4: Write compose.ts**

```ts
// frontend/src/features/compose/api/compose.ts
import { apiFetch, apiFetchJson } from '@/shared/api/client'
import type {
  ComposeDeployment, ComposeTemplate, DeploymentCreateBody, NodeRef,
  TemplateBody, TemplateSaveResult,
} from './types'

const J = { 'Content-Type': 'application/json' }

export function listTemplates(tag?: string): Promise<ComposeTemplate[]> {
  const q = tag ? `?tag=${encodeURIComponent(tag)}` : ''
  return apiFetchJson<ComposeTemplate[]>(`/api/compose/templates${q}`)
}
export function getTemplate(id: string): Promise<ComposeTemplate> {
  return apiFetchJson<ComposeTemplate>(`/api/compose/templates/${encodeURIComponent(id)}`)
}
export function createTemplate(body: TemplateBody & { id: string }): Promise<TemplateSaveResult> {
  return apiFetchJson<TemplateSaveResult>('/api/compose/templates', {
    method: 'POST', headers: J, body: JSON.stringify(body),
  })
}
export function updateTemplate(id: string, body: TemplateBody): Promise<TemplateSaveResult> {
  return apiFetchJson<TemplateSaveResult>(`/api/compose/templates/${encodeURIComponent(id)}`, {
    method: 'PUT', headers: J, body: JSON.stringify(body),
  })
}
export async function deleteTemplate(id: string): Promise<void> {
  await apiFetch(`/api/compose/templates/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function listNodes(): Promise<NodeRef[]> {
  return apiFetchJson<NodeRef[]>('/api/compose/nodes')
}

export function listDeployments(): Promise<ComposeDeployment[]> {
  return apiFetchJson<ComposeDeployment[]>('/api/compose/deployments')
}
export function createDeployment(body: DeploymentCreateBody): Promise<ComposeDeployment> {
  return apiFetchJson<ComposeDeployment>('/api/compose/deployments', {
    method: 'POST', headers: J, body: JSON.stringify(body),
  })
}
export async function deploymentAction(
  id: string, action: 'stop' | 'start' | 'restart',
): Promise<void> {
  await apiFetchJson(`/api/compose/deployments/${encodeURIComponent(id)}/${action}`, { method: 'POST' })
}
export async function deleteDeployment(id: string): Promise<void> {
  await apiFetch(`/api/compose/deployments/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
export function deploymentLogs(
  id: string, opts: { service?: string; tail?: number } = {},
): Promise<{ output: string }> {
  const p = new URLSearchParams()
  if (opts.service) p.set('service', opts.service)
  p.set('tail', String(opts.tail ?? 200))
  return apiFetchJson<{ output: string }>(
    `/api/compose/deployments/${encodeURIComponent(id)}/logs?${p.toString()}`,
  )
}
export function deploymentStatus(id: string): Promise<{ deployment_id: string; status: string }> {
  return apiFetchJson(`/api/compose/deployments/${encodeURIComponent(id)}/status`)
}
```

- [ ] **Step 5: Run** `cd frontend && npm test -- src/features/compose/api/compose.test.ts && npx tsc --noEmit` → PASS + 0 erreur TS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/compose/api/
git commit -m "feat(compose-gallery): frontend types + client API"
```

---

### Task FE2: Hooks TanStack Query

**Files:**
- Create: `frontend/src/features/compose/hooks/useCompose.ts`
- Test: `frontend/src/features/compose/hooks/useCompose.test.tsx`

**Interfaces:**
- Consumes : Task FE1 client.
- Produces : `useTemplates(tag?)`, `useTemplate(id?)`, `useNodes()`, `useDeployments()`, `useSaveTemplate()`, `useDeleteTemplate()`, `useCreateDeployment()`, `useDeploymentAction()`, `useDeleteDeployment()`. `QK` constant `{templates, template(id), nodes, deployments}`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/compose/hooks/useCompose.test.tsx
import { describe, it, expect } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useTemplates } from './useCompose'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useTemplates', () => {
  it('loads templates from the API (MSW)', async () => {
    const { result } = renderHook(() => useTemplates(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.[0].id).toBe('browserless')
  })
})
```

Add an MSW handler in `frontend/src/test/handlers.ts`:
```ts
http.get('/api/compose/templates', () =>
  HttpResponse.json([
    { id: 'browserless', name: 'Browserless', description: '', tags: ['web'],
      version: '1', compose_content: 'services: {}', parameters: [], source: 'user' },
  ])),
```

- [ ] **Step 2: Run** `cd frontend && npm test -- src/features/compose/hooks/useCompose.test.tsx` → FAIL.

- [ ] **Step 3: Write the hooks** (follow `features/mcp/api.ts` + `features/profiles/hooks/useProfiles.ts` patterns)

```tsx
// frontend/src/features/compose/hooks/useCompose.ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import * as api from '../api/compose'
import type { DeploymentCreateBody, TemplateBody } from '../api/types'

const QK = {
  templates: (tag?: string) => ['compose', 'templates', tag ?? null] as const,
  template: (id?: string) => ['compose', 'template', id ?? null] as const,
  nodes: () => ['compose', 'nodes'] as const,
  deployments: () => ['compose', 'deployments'] as const,
}

export function useTemplates(tag?: string) {
  return useQuery({ queryKey: QK.templates(tag), queryFn: () => api.listTemplates(tag), staleTime: 30_000 })
}
export function useTemplate(id?: string) {
  return useQuery({ queryKey: QK.template(id), queryFn: () => api.getTemplate(id!), enabled: Boolean(id) })
}
export function useNodes() {
  return useQuery({ queryKey: QK.nodes(), queryFn: api.listNodes, staleTime: 60_000 })
}
export function useDeployments() {
  return useQuery({ queryKey: QK.deployments(), queryFn: api.listDeployments, refetchInterval: 10_000 })
}

export function useSaveTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body, create }: { id: string; body: TemplateBody; create: boolean }) =>
      create ? api.createTemplate({ ...body, id }) : api.updateTemplate(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['compose', 'templates'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}
export function useDeleteTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.deleteTemplate,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['compose', 'templates'] }),
    onError: (e: Error) => toast.error(e.message),
  })
}
export function useCreateDeployment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: DeploymentCreateBody) => api.createDeployment(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.deployments() }),
    // pas de toast ici : le PortConflict 409 est géré dans le dialogue (pré-remplir le port)
  })
}
export function useDeploymentAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'stop' | 'start' | 'restart' }) =>
      api.deploymentAction(id, action),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.deployments() }),
    onError: (e: Error) => toast.error(e.message),
  })
}
export function useDeleteDeployment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.deleteDeployment,
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.deployments() }),
    onError: (e: Error) => toast.error(e.message),
  })
}
```

- [ ] **Step 4: Run** `cd frontend && npm test -- src/features/compose/hooks/useCompose.test.tsx && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/compose/hooks/ frontend/src/test/handlers.ts
git commit -m "feat(compose-gallery): frontend hooks TanStack Query"
```

---

### Task FE3: i18n + navigation + routes

**Files:**
- Modify: `frontend/src/i18n/en.json`, `frontend/src/i18n/fr.json`, `frontend/src/shared/layouts/AppShell.tsx`, `frontend/src/router.tsx`
- Test: `frontend/src/features/compose/__tests__/nav.test.tsx`

**Interfaces:**
- Produces : clé i18n `compose.*` (en+fr) ; lien rail `/compose` (user) + item dropdown admin `/admin/compose` ; routes `/compose` → `ComposeGallery` et `/admin/compose` → `AdminCompose` (sous `AdminGuard`). Crée des **stubs** `ComposeGallery`/`AdminCompose` (remplis aux tâches FE6/FE7) pour que les routes compilent.

- [ ] **Step 1: Add i18n keys** (en.json + fr.json — mêmes clés)

en.json (ajouter une section `compose`):
```json
"compose": {
  "title": "Docker Compose",
  "gallery": "Gallery",
  "deployments": "Deployments",
  "deploy": "Deploy",
  "admin": { "title": "Compose templates", "new": "New template", "navLabel": "Compose templates" },
  "form": { "name": "Name", "description": "Description", "node": "Target node", "yaml": "docker-compose.yml" },
  "deployDialog": { "title": "Deploy {{name}}", "submit": "Deploy", "portConflict": "Port {{ports}} already in use; suggested: {{suggestion}}" },
  "status": { "running": "running", "partial": "partial", "stopped": "stopped", "error": "error", "created": "created" },
  "actions": { "stop": "Stop", "start": "Start", "restart": "Restart", "down": "Tear down", "logs": "Logs" },
  "empty": { "templates": "No templates yet.", "deployments": "No deployments yet." },
  "delete": { "confirm": "Delete?", "cancel": "Cancel", "ok": "Delete" }
}
```
fr.json (mêmes clés, valeurs FR): title "Docker Compose", gallery "Galerie", deployments "Déploiements", deploy "Déployer", admin.title "Templates Compose", admin.new "Nouveau template", admin.navLabel "Templates Compose", form.node "Nœud cible", form.yaml "docker-compose.yml", deployDialog.title "Déployer {{name}}", deployDialog.portConflict "Port {{ports}} déjà utilisé ; suggéré : {{suggestion}}", status.* (running/partial/stopped/error/created identiques ou traduits), actions.* (Arrêter/Démarrer/Redémarrer/Détruire/Logs), empty.templates "Aucun template.", empty.deployments "Aucun déploiement.", delete.* (Supprimer ?/Annuler/Supprimer).

- [ ] **Step 2: Create page stubs**

```tsx
// frontend/src/features/compose/ComposeGallery.tsx
export default function ComposeGallery() {
  return <div className="p-6" data-testid="compose-gallery" />
}
```
```tsx
// frontend/src/features/compose/AdminCompose.tsx
export default function AdminCompose() {
  return <div className="p-6" data-testid="admin-compose" />
}
```

- [ ] **Step 3: Add nav link + admin item** (`AppShell.tsx`)

Importer une icône (`import { Container } from 'lucide-react'`), ajouter dans le rail user (à côté des autres `NavLink`):
```tsx
<NavLink to="/compose" className={({ isActive }) => cn(RAIL_LINK, isActive && RAIL_ACTIVE)} title={t('compose.title')}>
  <Container size={18} />
</NavLink>
```
Et dans le bloc `{isAdmin && (...)}` du dropdown, un item:
```tsx
<DropdownMenuItem onClick={() => navigate('/admin/compose')}>{t('compose.admin.navLabel')}</DropdownMenuItem>
```

- [ ] **Step 4: Add routes** (`router.tsx`, dans les `children` de l'`AppShell`)

```tsx
{ path: '/compose', element: <Wrap><ComposeGallery /></Wrap> },
{ path: '/admin/compose', element: <AdminGuard><Wrap><AdminCompose /></Wrap></AdminGuard> },
```
Avec les imports `ComposeGallery`/`AdminCompose` en tête (suivre le style d'import des autres pages).

- [ ] **Step 5: Write the nav test**

```tsx
// frontend/src/features/compose/__tests__/nav.test.tsx
import { describe, it, expect } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import ComposeGallery from '../ComposeGallery'

describe('ComposeGallery route stub', () => {
  it('renders the gallery container', () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
    const { getByTestId } = renderWithProviders(<ComposeGallery />, { route: '/compose' })
    expect(getByTestId('compose-gallery')).toBeInTheDocument()
  })
})
```

- [ ] **Step 6: Run** `cd frontend && npm test -- src/features/compose/__tests__/nav.test.tsx && npx tsc --noEmit && npx eslint src/features/compose src/shared/layouts/AppShell.tsx src/router.tsx` (ou le lint configuré du projet) → vert.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/i18n/ frontend/src/shared/layouts/AppShell.tsx frontend/src/router.tsx frontend/src/features/compose/
git commit -m "feat(compose-gallery): i18n + navigation + routes (stubs pages)"
```

---

### Task FE4: Éditeur YAML (`YamlEditor`)

**Files:**
- Create: `frontend/src/features/compose/components/YamlEditor.tsx`
- Test: `frontend/src/features/compose/components/YamlEditor.test.tsx`

**Interfaces:**
- Produces : `YamlEditor({ value, onChange, minHeight? })` — textarea + coloration Prism YAML, calqué sur `features/profiles/components/JsonEditor.tsx` mais grammaire `Prism.languages.yaml` (importer `prismjs/components/prism-yaml`).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/compose/components/YamlEditor.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import YamlEditor from './YamlEditor'

describe('YamlEditor', () => {
  it('renders value and emits onChange', () => {
    const onChange = vi.fn()
    const { container } = render(<YamlEditor value="services: {}" onChange={onChange} />)
    const ta = container.querySelector('textarea')!
    fireEvent.change(ta, { target: { value: 'services:\n  a: {}' } })
    expect(onChange).toHaveBeenCalledWith('services:\n  a: {}')
  })
})
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** (copier la structure de `JsonEditor.tsx` : grille `<pre aria-hidden>` colorée + `<textarea>` transparent en overlay ; remplacer `Prism.languages.json` par `Prism.languages.yaml` après `import 'prismjs/components/prism-yaml'`). Palette : réutiliser celle de JsonEditor (property/string/number/etc.). Props `{ value: string; onChange: (v: string) => void; minHeight?: string }`.

- [ ] **Step 4: Run** `cd frontend && npm test -- src/features/compose/components/YamlEditor.test.tsx && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/compose/components/YamlEditor.tsx frontend/src/features/compose/components/YamlEditor.test.tsx
git commit -m "feat(compose-gallery): éditeur YAML (Prism)"
```

---

### Task FE5: Formulaire dynamique de paramètres (`ParametersForm`)

**Files:**
- Create: `frontend/src/features/compose/components/ParametersForm.tsx`
- Test: `frontend/src/features/compose/components/ParametersForm.test.tsx`

**Interfaces:**
- Consumes : `ComposeParam[]` (types FE1), shadcn `Input`/`Select`/`Label` (+ radio-group pour bool).
- Produces : `ParametersForm({ parameters, values, onChange, errors? })` — rend un widget par paramètre selon `type` : `string`→Input ; `number`/`port`→Input type=number ; `bool`→RadioGroup true/false (pas de Checkbox shadcn dispo) ; `enum`→Select(options) ; `secret`→Input texte avec placeholder `${vault://...}` (+ aide `secret_ref_hint`). `values: Record<string,string>`, `onChange(key, value)`. Affiche `label`, `description`, `*` si `required`, et `errors[key]` si fourni.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/compose/components/ParametersForm.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ParametersForm from './ParametersForm'
import type { ComposeParam } from '../api/types'

const params: ComposeParam[] = [
  { key: 'WEB_PORT', label: 'Port', type: 'port', required: true },
  { key: 'MODE', label: 'Mode', type: 'enum', required: false, options: ['a', 'b'] },
  { key: 'TOKEN', label: 'Token', type: 'secret', required: true },
]

describe('ParametersForm', () => {
  it('renders a widget per param and emits onChange', () => {
    const onChange = vi.fn()
    render(<ParametersForm parameters={params} values={{}} onChange={onChange} />)
    expect(screen.getByLabelText(/Port/)).toBeInTheDocument()
    const port = screen.getByLabelText(/Port/)
    fireEvent.change(port, { target: { value: '3000' } })
    expect(onChange).toHaveBeenCalledWith('WEB_PORT', '3000')
  })
  it('secret field hints a vault reference', () => {
    render(<ParametersForm parameters={params} values={{}} onChange={() => {}} />)
    expect(screen.getByPlaceholderText(/vault:\/\//)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `ParametersForm.tsx` (map sur `parameters`, switch sur `type`, widgets shadcn ; `port`/`number` → `<Input type="number">` ; `secret` → `<Input placeholder="${vault://bloc/nom}">` ; `enum` → `<Select>` ; `bool` → `<RadioGroup>` true/false ; sinon `<Input>`). ≤ 300 lignes.

- [ ] **Step 4: Run** `cd frontend && npm test -- src/features/compose/components/ParametersForm.test.tsx && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/compose/components/ParametersForm.tsx frontend/src/features/compose/components/ParametersForm.test.tsx
git commit -m "feat(compose-gallery): formulaire dynamique de paramètres"
```

---

### Task FE6: Page galerie + déploiements (user `/compose`)

**Files:**
- Modify: `frontend/src/features/compose/ComposeGallery.tsx` (remplace le stub)
- Create: `frontend/src/features/compose/components/DeployDialog.tsx`, `frontend/src/features/compose/components/DeploymentsPanel.tsx`, `frontend/src/features/compose/components/LogsDialog.tsx`
- Test: `frontend/src/features/compose/__tests__/ComposeGallery.test.tsx`

**Interfaces:**
- Consumes : hooks FE2, `ParametersForm` FE5, shadcn Card/Dialog/Button/Badge/Select/Tabs.
- Produces : `ComposeGallery` à deux onglets (Tabs) « Galerie » (cartes de templates → bouton Deploy ouvrant `DeployDialog`) et « Déploiements » (`DeploymentsPanel`). `DeployDialog({ template, open, onOpenChange })` : sélection nœud (`useNodes`), `ParametersForm` depuis `template.parameters`, soumission `useCreateDeployment` ; sur 409 PortConflict (parser `err.message` JSON → `detail.suggestion`) pré-remplir le port + afficher le message. `DeploymentsPanel` : `useDeployments`, par déploiement → `Badge` status, boutons start/stop/restart/down (`useDeploymentAction`/`useDeleteDeployment`, confirm pour down), bouton Logs → `LogsDialog` (`deploymentLogs`).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/compose/__tests__/ComposeGallery.test.tsx
import { describe, it, expect } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import ComposeGallery from '../ComposeGallery'

describe('ComposeGallery', () => {
  it('lists templates from the API', async () => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
    const { findByText } = renderWithProviders(<ComposeGallery />, { route: '/compose' })
    expect(await findByText('Browserless')).toBeInTheDocument()
  })
})
```
Ajouter aux handlers MSW : `GET /api/compose/nodes` → `[{node_id:'n1',name:'n1'}]`, `GET /api/compose/deployments` → `[]`.

- [ ] **Step 2: Run** → FAIL (stub n'affiche rien).

- [ ] **Step 3: Implement** `ComposeGallery` (Tabs Galerie/Déploiements ; grille de cards via `useTemplates`, bouton Deploy → `DeployDialog`), `DeployDialog`, `DeploymentsPanel`, `LogsDialog`. Suivre les patterns `ProfileList` (cards + Dialog) et `MCPBackends`. Gestion 409 dans `DeployDialog` :
```tsx
try { await createDeployment.mutateAsync(body); onOpenChange(false) }
catch (e) {
  const detail = parseDetail(e)  // JSON.parse(err.message) → {error,conflicts,suggestion} sinon null
  if (detail?.error === 'port_conflict') { setServerError(t('compose.deployDialog.portConflict', { ports: detail.conflicts.join(','), suggestion: detail.suggestion })) }
  else setServerError((e as Error).message)
}
```

- [ ] **Step 4: Run** `cd frontend && npm test -- src/features/compose/__tests__/ComposeGallery.test.tsx && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/compose/ frontend/src/test/handlers.ts
git commit -m "feat(compose-gallery): page galerie + déploiements (user)"
```

---

### Task FE7: Page admin templates (`/admin/compose`)

**Files:**
- Modify: `frontend/src/features/compose/AdminCompose.tsx` (remplace le stub)
- Create: `frontend/src/features/compose/components/TemplateEditor.tsx`
- Test: `frontend/src/features/compose/__tests__/AdminCompose.test.tsx`

**Interfaces:**
- Consumes : hooks FE2 (`useTemplates`, `useSaveTemplate`, `useDeleteTemplate`), `YamlEditor` FE4, shadcn.
- Produces : `AdminCompose` — liste des templates (cards) + bouton « Nouveau » + suppression (Dialog confirm) ; ouvre `TemplateEditor`. `TemplateEditor({ template?, open, onOpenChange })` : champs `name`/`description`/`tags`(csv)/`version`/`id`(slug, à la création) + `YamlEditor` pour `compose_content` + édition de la liste `parameters` (ajout/suppr lignes : key,label,type,required,default,options) ; soumission `useSaveTemplate` ; affiche `warnings` retournés (lint `:latest`) en alerte non bloquante ; erreurs 422/409 → `serverError`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/compose/__tests__/AdminCompose.test.tsx
import { describe, it, expect } from 'vitest'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import AdminCompose from '../AdminCompose'

describe('AdminCompose', () => {
  it('lists templates for an admin', async () => {
    useUserStore.setState({ user: { login: 'root', roles: ['admin'] } })
    const { findByText } = renderWithProviders(<AdminCompose />, { route: '/admin/compose' })
    expect(await findByText('Browserless')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** `AdminCompose` + `TemplateEditor` (patterns `ProfileList`/`ProfileEditor`). Le `TemplateEditor` envoie `useSaveTemplate({ id, body, create })` ; afficher `result.warnings` via toast/alerte ; à la création, champ `id` (slug) validé `^[a-z0-9][a-z0-9-]{0,40}[a-z0-9]$`.

- [ ] **Step 4: Run** `cd frontend && npm test -- src/features/compose/__tests__/AdminCompose.test.tsx && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Full frontend gate + commit**

```bash
cd frontend && npm test -- src/features/compose && npx tsc --noEmit
git add frontend/src/features/compose/
git commit -m "feat(compose-gallery): page admin templates + éditeur (lot frontend complet)"
```

---

## Self-Review (effectuée)

**Spec coverage (design §8)** : galerie templates (FE6), éditeur template + YAML + params + lint warnings (FE4/FE5/FE7), dialogue d'instanciation (nœud + params dynamiques + conflit port 409) (FE6), vue déploiements + statut + start/stop/restart/down + logs (FE6), RBAC admin/dev (FE3 routes + BE1), nav visible (FE3). ✓
**Prérequis backend** : lecture templates user + `GET /nodes` (BE1) — sans quoi le dev ne peut ni lister ni choisir un nœud. ✓
**Placeholder scan** : code complet pour les contrats (types/api/hooks) ; pages décrites avec patterns de référence + code des points délicats (409, switch widgets, overlay YAML). Les boucles de rendu suivent `ProfileList`/`MCPBackends` (référencés explicitement).
**Type consistency** : `ComposeTemplate`/`ComposeParam`/`ComposeDeployment`/`NodeRef`/`DeploymentCreateBody` (FE1) consommés par hooks (FE2) et pages (FE6/FE7) ; endpoints alignés sur le backend réel `/api/compose/*`.

> **Limite tests** : Vitest/MSW couvrent rendu + appels mockés. Le rendu réel dans l'app complète (router+AppShell) et le flux E2E contre le vrai backend se valident manuellement / en staging.

---

## Execution Handoff
Subagent-driven (recommandé), un subagent par tâche, review après chaque.
