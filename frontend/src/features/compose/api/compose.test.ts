import { describe, it, expect } from 'vitest'
import { http, HttpResponse } from 'msw'
import type { ComposeTemplate, ComposeDeployment } from './types'
import { deleteTemplate, deleteDeployment } from './compose'
import { ApiError } from '@/shared/api/client'
import { server } from '@/test/server'

describe('compose types', () => {
  it('template shape compiles', () => {
    const t: ComposeTemplate = {
      id: 'browserless', name: 'B', description: '', tags: ['web'], version: '1',
      compose_content: 'services: {}', parameters: [], source: 'user', auto_start: false,
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

describe('deleteTemplate', () => {
  it('throws ApiError on 409', async () => {
    server.use(
      http.delete('/api/compose/templates/:id', () =>
        new HttpResponse('template already deployed', { status: 409 }),
      ),
    )
    await expect(deleteTemplate('browserless')).rejects.toBeInstanceOf(ApiError)
    await expect(deleteTemplate('browserless')).rejects.toMatchObject({ status: 409 })
  })

  it('resolves successfully on 204', async () => {
    await expect(deleteTemplate('browserless')).resolves.toBeUndefined()
  })
})

describe('deleteDeployment', () => {
  it('throws ApiError on 409', async () => {
    server.use(
      http.delete('/api/compose/deployments/:id', () =>
        new HttpResponse('deployment is active', { status: 409 }),
      ),
    )
    await expect(deleteDeployment('dep1')).rejects.toBeInstanceOf(ApiError)
    await expect(deleteDeployment('dep1')).rejects.toMatchObject({ status: 409 })
  })
})
