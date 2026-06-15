import { http, HttpResponse } from 'msw'

export const handlers = [
  http.get('/me', () =>
    HttpResponse.json({ login: 'alice', roles: ['dev'] })
  ),
  http.get('/me/workspaces', () => HttpResponse.json([])),
  http.get('/me/git-credentials', () => HttpResponse.json([])),
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
      { name: 'ssh-dev', type: 'ssh', default: false, address: 'debian@192.168.10.175', key_path: '/data/keys/hosts/ssh_dev_ed25519' },
    ])
  ),
  http.get('/admin/recipes', () => HttpResponse.json([])),
  http.delete('/admin/recipes/:id', () => HttpResponse.json({ deleted: 'ok' })),
  http.delete('/me/recipes/:id', () => HttpResponse.json({ deleted: 'ok' })),
  http.get('/admin/recipe-sources', () => HttpResponse.json({ sources: [] })),
  http.get('/admin/recipe-sources/preview', () => HttpResponse.json({ recipes: [] })),

  // Handlers profiles
  http.get('/profiles', () =>
    HttpResponse.json([
      {
        slug: 'frontend-react',
        scope: 'user',
        name: 'Frontend React',
        description: 'Stack React',
        extension_count: 1,
        editable: true,
      },
      {
        slug: 'python-dev',
        scope: 'shared',
        name: 'Python Dev',
        description: 'Python stack',
        extension_count: 2,
        editable: false,
      },
    ])
  ),
  http.get('/profiles/:scope/:slug', ({ params }) =>
    HttpResponse.json({
      slug: params.slug,
      scope: params.scope,
      name: 'Frontend React',
      description: 'Stack React',
      extensions: ['esbenp.prettier-vscode'],
      settings: {},
    })
  ),
  http.post('/profiles/shared/:slug/fork', () =>
    HttpResponse.json(
      {
        slug: 'python-dev-2',
        scope: 'user',
        name: 'Python Dev',
        description: 'Python stack',
        extensions: [],
        settings: {},
      },
      { status: 201 }
    )
  ),
  http.post('/profiles', () =>
    HttpResponse.json(
      {
        slug: 'new-profile',
        scope: 'user',
        name: 'New Profile',
        description: '',
        extensions: [],
        settings: {},
      },
      { status: 201 }
    )
  ),
  http.put('/profiles/:slug', ({ params }) =>
    HttpResponse.json({
      slug: params.slug,
      scope: 'user',
      name: 'Updated',
      description: '',
      extensions: [],
      settings: {},
    })
  ),
  http.delete('/profiles/:slug', () => new HttpResponse(null, { status: 204 })),
  // Admin profiles
  http.get('/admin/profiles', () =>
    HttpResponse.json([
      {
        slug: 'python-dev',
        scope: 'shared',
        name: 'Python Dev',
        description: 'Python stack',
        extension_count: 2,
        editable: true,
      },
    ])
  ),
  http.post('/admin/profiles', () =>
    HttpResponse.json(
      { slug: 'new-shared', scope: 'shared', name: 'New', description: '', extensions: [], settings: {} },
      { status: 201 }
    )
  ),
  http.put('/admin/profiles/:slug', ({ params }) =>
    HttpResponse.json({
      slug: params.slug,
      scope: 'shared',
      name: 'Updated',
      description: '',
      extensions: [],
      settings: {},
    })
  ),
  http.delete('/admin/profiles/:slug', () => new HttpResponse(null, { status: 204 })),

  // Handlers plugins
  http.get('/plugins/search', () =>
    HttpResponse.json({
      total: 1,
      offset: 0,
      items: [{
        id: 'ms-python.python',
        namespace: 'ms-python',
        name: 'python',
        display_name: 'Python',
        description: 'Python language support',
        version: '2024.0.1',
        downloads: 100000,
        rating: 4.5,
        icon_url: null,
      }],
    })
  ),
  http.get('/plugins/:namespace/:name/readme', () =>
    new HttpResponse('', { headers: { 'Content-Type': 'text/markdown' } })
  ),
  http.get('/plugins/:namespace/:name', () =>
    HttpResponse.json({
      id: 'ms-python.python',
      namespace: 'ms-python',
      name: 'python',
      display_name: 'Python',
      description: 'Python language support',
      version: '2024.0.1',
      downloads: 100000,
      rating: 4.5,
      icon_url: null,
      categories: ['Programming Languages'],
      tags: ['python'],
      license: null,
      readme_url: null,
    })
  ),
]
