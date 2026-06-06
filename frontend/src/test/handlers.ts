import { http, HttpResponse } from 'msw'

export const handlers = [
  http.get('/me', () =>
    HttpResponse.json({ login: 'alice', roles: ['dev'] })
  ),
  http.get('/me/workspaces', () => HttpResponse.json([])),
  http.post('/me/workspaces', () => HttpResponse.json({}, { status: 201 })),
  http.delete('/me/workspaces/:name', () => HttpResponse.json({ deleted: 'ok' })),
  http.post('/me/workspaces/:name/up', () =>
    HttpResponse.json({ ws_id: 'alice-myapp', status: 'provisioning' }, { status: 202 })
  ),
  http.post('/me/workspaces/:name/stop', () =>
    HttpResponse.json({ ws_id: 'alice-myapp', status: 'stopped' })
  ),
  http.post('/me/workspaces/:name/delete', () =>
    HttpResponse.json({ ws_id: 'alice-myapp', deleted: true })
  ),
  http.get('/me/workspaces/:name/status', () =>
    HttpResponse.json({ ws_id: 'alice-myapp', status: 'running', url: 'https://alice-myapp.dev.yoops.org' })
  ),
  http.get('/recipes', () =>
    HttpResponse.json([
      { id: 'claude-code', version: '1.0.0', description: 'Claude Code CLI', installs_after: [], requires_secrets: [{ path: 'llm/anthropic_key', env: 'ANTHROPIC_API_KEY' }] },
      { id: 'aider', version: '1.0.0', description: 'Aider AI pair programmer', installs_after: [], requires_secrets: [{ path: 'llm/anthropic_key', env: 'ANTHROPIC_API_KEY' }] },
    ])
  ),
  http.get('/me/recipes', () => HttpResponse.json([])),
  http.get('/admin/hosts', () =>
    HttpResponse.json([
      { name: 'pve1', type: 'docker-tls', default: true, docker_host: 'tcp://192.168.1.50:2376' },
      { name: 'pve2', type: 'docker-tls', default: false, docker_host: 'tcp://192.168.1.51:2376' },
    ])
  ),
  http.get('/admin/recipes', () => HttpResponse.json([])),
  http.delete('/admin/recipes/:id', () => HttpResponse.json({ deleted: 'ok' })),
  http.delete('/me/recipes/:id', () => HttpResponse.json({ deleted: 'ok' })),
]
