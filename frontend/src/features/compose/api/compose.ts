import { apiFetch, apiFetchJson, ApiError } from '@/shared/api/client'
import type {
  AutoStartUpdateBody, ComposeDeployment, ComposeTemplate, DeploymentCreateBody, NodeRef,
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
  const res = await apiFetch(`/api/compose/templates/${encodeURIComponent(id)}`, { method: 'DELETE' })
  if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
}

export function setAutoStart(
  templateId: string, body: AutoStartUpdateBody,
): Promise<{ template_id: string; enabled: boolean }> {
  return apiFetchJson(`/api/compose/templates/${encodeURIComponent(templateId)}/auto-start`, {
    method: 'PUT', headers: J, body: JSON.stringify(body),
  })
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
  const res = await apiFetch(`/api/compose/deployments/${encodeURIComponent(id)}`, { method: 'DELETE' })
  if (!res.ok) throw new ApiError(res.status, (await res.text().catch(() => '')) || res.statusText)
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
export function getDeploymentMessage(id: string): Promise<import('./types').DeploymentMessage> {
  return apiFetchJson(`/api/compose/deployments/${encodeURIComponent(id)}/message`)
}
