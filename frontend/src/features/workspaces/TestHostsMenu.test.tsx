import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import TestHostsMenu from './TestHostsMenu'

const ONE_HOST = [
  { alias: 'test1', name: 'host-test-114-1', ip: '192.168.10.160', vmid: '114' },
]

describe('TestHostsMenu', () => {
  it('ne rend rien quand aucune machine de test n\'est attachée', async () => {
    server.use(http.get('/me/workspaces/ws1/test-hosts', () => HttpResponse.json([])))
    renderWithProviders(<TestHostsMenu wsName="ws1" enabled onOpenSsh={() => {}} />)
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByRole('button', { name: /ssh test/i })).toBeNull()
  })

  it('affiche le bouton SSH test quand des machines existent', async () => {
    server.use(http.get('/me/workspaces/ws1/test-hosts', () => HttpResponse.json(ONE_HOST)))
    renderWithProviders(<TestHostsMenu wsName="ws1" enabled onOpenSsh={() => {}} />)
    expect(await screen.findByRole('button', { name: /ssh test/i })).toBeInTheDocument()
  })
})
