import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { render } from '@testing-library/react'
import i18n from '@/i18n'
import { server } from '@/test/server'
import WorkspaceTerminals from './WorkspaceTerminals'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const router = createMemoryRouter(
    [{ path: '/workspaces/:wsName/terminals', element: <I18nextProvider i18n={i18n}><WorkspaceTerminals /></I18nextProvider> }],
    { initialEntries: ['/workspaces/myapp/terminals'] }
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

describe('bug 044 : validation client du nom de session', () => {
  it('rejette un nom de session invalide et n\'appelle pas le backend', async () => {
    server.use(
      http.get('/me/workspaces/:name/sessions', () => HttpResponse.json([])),
      http.get('/me/workspaces/:name/start-recipes', () => HttpResponse.json([])),
    )
    let createCalled = false
    server.use(
      http.post('/me/workspaces/:name/sessions', () => {
        createCalled = true
        return HttpResponse.json({ name: 's1' }, { status: 201 })
      })
    )
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getAllByText(/aucune session|no active session/i).length).toBeGreaterThan(0))
    await user.click(screen.getByRole('button', { name: /créer une session|create a session/i }))

    const input = await screen.findByLabelText(/^nom$|^name$/i)
    await user.clear(input)
    await user.type(input, 'a/b c#')
    await user.click(screen.getByRole('button', { name: /créer|create/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(createCalled).toBe(false)
  })

  it('accepte un nom de session valide et appelle le backend', async () => {
    server.use(
      http.get('/me/workspaces/:name/sessions', () => HttpResponse.json([])),
      http.get('/me/workspaces/:name/start-recipes', () => HttpResponse.json([])),
    )
    let createdName = ''
    server.use(
      http.post('/me/workspaces/:name/sessions', async ({ request }) => {
        const body = (await request.json()) as { name: string }
        createdName = body.name
        return HttpResponse.json({ name: body.name }, { status: 201 })
      })
    )
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getAllByText(/aucune session|no active session/i).length).toBeGreaterThan(0))
    await user.click(screen.getByRole('button', { name: /créer une session|create a session/i }))

    const input = await screen.findByLabelText(/^nom$|^name$/i)
    await user.clear(input)
    await user.type(input, 'myapp1')
    await user.click(screen.getByRole('button', { name: /créer|create/i }))

    await waitFor(() => expect(createdName).toBe('myapp1'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
