import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import * as api from '../api/compose'
import type { DeploymentCreateBody, TemplateBody } from '../api/types'

const QK = {
  templates: (tag?: string) => ['compose', 'templates', tag ?? null] as const,
  template: (id?: string) => ['compose', 'template', id ?? null] as const,
  nodes: () => ['compose', 'nodes'] as const,
  deployments: () => ['compose', 'deployments'] as const,
  logs: (id: string) => ['compose', 'logs', id] as const,
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

export function useDeploymentLogs(uid: string, enabled: boolean) {
  return useQuery({
    queryKey: QK.logs(uid),
    queryFn: () => api.deploymentLogs(uid, { tail: 300 }),
    enabled,
    staleTime: 0,
    refetchInterval: enabled ? 5_000 : false,
  })
}

export function useSaveTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body, create }: { id: string; body: TemplateBody; create: boolean }) =>
      create ? api.createTemplate({ ...body, id }) : api.updateTemplate(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['compose', 'templates'] }),
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
    mutationFn: ({ uid, action }: { uid: string; action: 'stop' | 'start' | 'restart' }) =>
      api.deploymentAction(uid, action),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.deployments() }),
    onError: (e: Error) => toast.error(e.message),
  })
}
export function useDeleteDeployment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (uid: string) => api.deleteDeployment(uid),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.deployments() }),
    onError: (e: Error) => toast.error(e.message),
  })
}
export function useDeploymentMessage(uid: string, enabled: boolean) {
  return useQuery({
    queryKey: ['compose', 'message', uid] as const,
    queryFn: () => api.getDeploymentMessage(uid),
    enabled,
    retry: false,
    staleTime: 60_000,
  })
}
