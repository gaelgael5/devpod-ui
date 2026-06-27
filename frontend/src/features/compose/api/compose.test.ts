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
