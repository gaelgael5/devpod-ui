/**
 * Recettes applicables a une machine.
 *
 * Ce qui compte ici : ne proposer que ce qui vise cette machine, distinguer
 * « posee » de « posee dans une version ancienne », et surtout rendre compte
 * d'une application qui dure — une recette de host peut peser 20 Go.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import { server } from '@/test/server'
import HostRecipesDialog from './HostRecipesDialog'

function renderDialog(host = 'test1') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <HostRecipesDialog hostName={host} onClose={vi.fn()} />
      </I18nextProvider>
    </QueryClientProvider>,
  )
}

function catalogue(body: unknown) {
  server.use(http.get('/admin/hosts/:name/recipes', () => HttpResponse.json(body)))
}

describe('HostRecipesDialog — routes selon le proprietaire', () => {
  /**
   * Poser une recette de la galerie sur SA machine de test ne passe pas par un
   * administrateur : la garde cote serveur est la PROPRIETE, pas le role. Le
   * dialog doit donc viser `/me` quand un workspace est fourni.
   */
  function renderAvecWorkspace(ws?: string) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    return render(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <HostRecipesDialog hostName="test1" wsName={ws} onClose={vi.fn()} />
        </I18nextProvider>
      </QueryClientProvider>,
    )
  }

  it('vise /me quand la machine appartient a un workspace', async () => {
    let vue: string | null = null
    server.use(
      http.get('/me/workspaces/:ws/test-hosts/:host/recipes', ({ request }) => {
        vue = new URL(request.url).pathname
        return HttpResponse.json({ installed: {}, available: [] })
      }),
    )

    renderAvecWorkspace('termix-mobile')

    await waitFor(() => expect(vue).toBe('/me/workspaces/termix-mobile/test-hosts/test1/recipes'))
  })

  it('vise /admin sans workspace', async () => {
    let vue: string | null = null
    server.use(
      http.get('/admin/hosts/:host/recipes', ({ request }) => {
        vue = new URL(request.url).pathname
        return HttpResponse.json({ installed: {}, available: [] })
      }),
    )

    renderAvecWorkspace(undefined)

    await waitFor(() => expect(vue).toBe('/admin/hosts/test1/recipes'))
  })
})

describe('HostRecipesDialog', () => {
  it('liste les recettes applicables', async () => {
    catalogue({
      installed: {},
      available: [{ id: 'android-emulator', version: '1.0.0', description: 'SDK Android' }],
    })

    renderDialog()

    expect(await screen.findByTestId('recette-android-emulator')).toBeInTheDocument()
  })

  it('le dit quand aucune recette ne vise cette machine', async () => {
    // Une liste vide sans explication ressemble a une panne.
    catalogue({ installed: {}, available: [] })

    renderDialog()

    expect(await screen.findByTestId('aucune-recette')).toBeInTheDocument()
  })

  it('signale une recette deja posee dans la bonne version', async () => {
    catalogue({
      installed: { 'android-emulator': { version: '1.0.0', applied_at: '2026-08-24' } },
      available: [{ id: 'android-emulator', version: '1.0.0', description: '' }],
    })

    renderDialog()

    expect(await screen.findByTestId('etat-android-emulator')).toHaveTextContent(
      /installée|installed/i,
    )
  })

  it('distingue une version ancienne d’une version a jour', async () => {
    // « Posee » ne suffit pas : une version perimee doit se voir d'un coup d'oeil.
    catalogue({
      installed: { 'android-emulator': { version: '0.9.0', applied_at: '2026-01-01' } },
      available: [{ id: 'android-emulator', version: '1.0.0', description: '' }],
    })

    renderDialog()

    expect(await screen.findByTestId('etat-android-emulator')).toHaveTextContent('0.9.0')
  })

  it('n’envoie aucun corps quand il n’y a pas d’option', async () => {
    // Le parametre est optionnel cote serveur : un corps vide mal type valait
    // un 422 « Input should be a valid dictionary » pour rien.
    const user = userEvent.setup()
    let brut: string | null = null
    catalogue({
      installed: {},
      available: [{ id: 'android-emulator', version: '1.0.0', description: '' }],
    })
    server.use(
      http.post('/admin/hosts/:name/recipes/:id', async ({ request }) => {
        brut = await request.text()
        return HttpResponse.json({ operation_id: 'op-1' }, { status: 202 })
      }),
    )
    renderDialog()

    await user.click(await screen.findByRole('button', { name: /appliquer|^apply$/i }))

    await waitFor(() => expect(brut).toBe(''))
  })

  it('rend compte de l’application jusqu’a son terme', async () => {
    // Sans ce suivi, l'interface lancerait 20 Go d'installation sans jamais
    // dire si elle a abouti.
    const user = userEvent.setup()
    catalogue({
      installed: {},
      available: [{ id: 'android-emulator', version: '1.0.0', description: '' }],
    })
    server.use(
      http.post('/admin/hosts/:name/recipes/:id', () =>
        HttpResponse.json({ operation_id: 'op-1' }, { status: 202 }),
      ),
      http.get('/admin/operations/op-1', () =>
        HttpResponse.json({ state: 'done', progress: 100, error: null }),
      ),
    )
    renderDialog()

    await user.click(await screen.findByRole('button', { name: /appliquer|^apply$/i }))

    await waitFor(() => expect(screen.getByTestId('suivi')).toHaveTextContent(/appliquée|applied/i))
  })

  it('montre l’erreur quand l’application est refusee', async () => {
    const user = userEvent.setup()
    catalogue({
      installed: {},
      available: [{ id: 'android-emulator', version: '1.0.0', description: '' }],
    })
    server.use(
      http.post('/admin/hosts/:name/recipes/:id', () =>
        HttpResponse.json({ detail: 'préconditions non satisfaites : /dev/kvm' }, { status: 422 }),
      ),
    )
    renderDialog()

    await user.click(await screen.findByRole('button', { name: /appliquer|^apply$/i }))

    expect(await screen.findByTestId('erreur-application')).toBeInTheDocument()
  })
})
