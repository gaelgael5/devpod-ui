import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import { useUserStore } from '@/store/user'
import WorkspaceCreate from './WorkspaceCreate'

describe('WorkspaceCreate', () => {
  it('affiche le formulaire sans source pré-remplie', () => {
    renderWithProviders(<WorkspaceCreate />)
    expect(screen.getByLabelText(/name|nom/i)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('github.com/org/repo')).not.toBeInTheDocument()
  })

  it('invalide un nom qui ne respecte pas la regex', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)
    await user.type(screen.getByLabelText(/name|nom/i), '../etc')
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      expect(screen.getAllByRole('alert').length).toBeGreaterThan(0)
    })
  })

  it('soumet le formulaire avec nom et source valides', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />, { route: '/workspaces/new' })
    await user.type(screen.getByLabelText(/name|nom/i), 'my-project')
    await user.click(screen.getByRole('button', { name: /ajouter|add source/i }))
    await user.type(screen.getByPlaceholderText('github.com/org/repo'), 'github.com/org/repo')
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })

  it('affiche une erreur 422 du serveur inline', async () => {
    server.use(
      http.post('/me/workspaces/:name/up', () =>
        HttpResponse.json({ detail: 'Invalid recipe id' }, { status: 422 })
      )
    )
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)
    await user.type(screen.getByLabelText(/name|nom/i), 'myapp')
    await user.click(screen.getByRole('button', { name: /ajouter|add source/i }))
    await user.type(screen.getByPlaceholderText('github.com/org/repo'), 'github.com/org/repo')
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      expect(screen.getByText(/invalid recipe/i)).toBeInTheDocument()
    })
  })

  it('permet d\'ajouter deux sources', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)
    const addBtn = screen.getByRole('button', { name: /ajouter|add source/i })
    await user.click(addBtn)
    await user.click(addBtn)
    const urlInputs = screen.getAllByPlaceholderText('github.com/org/repo')
    expect(urlInputs).toHaveLength(2)
  })

  it('soumet sans source (workspace sans git clone)', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />, { route: '/workspaces/new' })
    await user.type(screen.getByLabelText(/name|nom/i), 'my-project')
    // Pas de source ajoutée
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })

  it('valide que l\'URL de la source est requise quand une ligne est ajoutée', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)
    await user.type(screen.getByLabelText(/name|nom/i), 'my-project')
    await user.click(screen.getByRole('button', { name: /ajouter|add source/i }))
    // URL laissée vide
    await user.click(screen.getByRole('button', { name: /create|créer/i }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
  })

  it('affiche le toggle Générer une clé SSH', () => {
    renderWithProviders(<WorkspaceCreate />)
    expect(
      screen.getByRole('checkbox', { name: /générer.*clé ssh|generate.*ssh key/i })
    ).toBeInTheDocument()
  })

  it('passe generate_ssh_key=true dans le corps /up quand la case SSH est cochée', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/me/workspaces/:name/up', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ ws_id: 'alice-my-project', status: 'provisioning' }, { status: 202 })
      })
    )

    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />, { route: '/workspaces/new' })

    await user.type(screen.getByLabelText(/name|nom/i), 'my-project')
    await user.click(screen.getByRole('checkbox', { name: /générer.*clé ssh|generate.*ssh key/i }))
    await user.click(screen.getByRole('button', { name: /create|créer/i }))

    await waitFor(() => {
      expect(capturedBody).toBeDefined()
    })
    expect(capturedBody).toMatchObject({ generate_ssh_key: true })
  })
})

// MSW handlers fournissent GET /profiles avec 2 profils :
// - { slug: 'frontend-react', scope: 'user',   name: 'Frontend React' }
// - { slug: 'python-dev',     scope: 'shared', name: 'Python Dev'     }
// i18n en test = anglais : label "VSCode Profile", option vide "— no profile —", suffixe "(shared)"
//
// Radix Select génère un <select> natif aria-hidden en plus du trigger custom.
// jsdom ne supporte pas hasPointerCapture (utilisé par Radix pour le pointer tracking),
// donc on interagit avec le <select> natif via fireEvent.change pour changer la valeur.
describe('WorkspaceCreate — sélecteur profil', () => {
  beforeEach(() => {
    useUserStore.setState({ user: { login: 'alice', roles: ['dev'] } })
  })

  /** Retourne le <select> natif aria-hidden que Radix génère sous le hood. */
  function getProfileNativeSelect(): HTMLSelectElement {
    // Le select natif Radix a aria-hidden="true" et contient les options encodées scope:slug
    const selects = document.querySelectorAll<HTMLSelectElement>('select[aria-hidden="true"]')
    if (selects.length === 0) throw new Error('No native select found')
    // Le dernier select aria-hidden est celui du profil (les autres Select du form
    // ont les mêmes options mais ne sont présents que si des sources ou un host sont ajoutés)
    return selects[selects.length - 1]
  }

  it('affiche le label et l\'option "no profile" par défaut', async () => {
    renderWithProviders(<WorkspaceCreate />)
    // Le label "VSCode Profile" apparaît dès que les profils sont chargés
    expect(await screen.findByText('VSCode Profile')).toBeInTheDocument()
    // L'option par défaut rendue dans le span du trigger Radix
    const spans = screen.getAllByText('— no profile —')
    expect(spans.length).toBeGreaterThanOrEqual(1)
  })

  it('le select natif liste les profils user et partagés', async () => {
    renderWithProviders(<WorkspaceCreate />)
    await screen.findByText('VSCode Profile')

    const nativeSelect = getProfileNativeSelect()
    const options = Array.from(nativeSelect.options).map((o) => o.value)
    expect(options).toContain('user:frontend-react')
    expect(options).toContain('shared:python-dev')
  })

  it('création avec profil → profile inclus dans les deux requêtes', async () => {
    const capturedBodies: unknown[] = []
    server.use(
      http.post('/me/workspaces', async ({ request }) => {
        capturedBodies.push(await request.json())
        return HttpResponse.json({}, { status: 201 })
      }),
      http.post('/me/workspaces/:name/up', async ({ request }) => {
        capturedBodies.push(await request.json())
        return HttpResponse.json({ ws_id: 'alice-my-ws', status: 'provisioning' }, { status: 202 })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)

    await screen.findByText('VSCode Profile')

    await user.type(screen.getByLabelText(/^name$/i), 'my-ws')

    // Sélectionner Python Dev via le select natif Radix (évite le problème hasPointerCapture)
    fireEvent.change(getProfileNativeSelect(), { target: { value: 'shared:python-dev' } })

    await user.click(screen.getByRole('button', { name: /create workspace/i }))

    await waitFor(() => expect(capturedBodies).toHaveLength(2))
    const [specBody, upBody] = capturedBodies as Array<{ profile?: unknown }>
    expect(specBody.profile).toEqual({ scope: 'shared', slug: 'python-dev' })
    expect(upBody.profile).toEqual({ scope: 'shared', slug: 'python-dev' })
  })

  it('création sans profil → profile null dans les deux requêtes', async () => {
    const capturedBodies: unknown[] = []
    server.use(
      http.post('/me/workspaces', async ({ request }) => {
        capturedBodies.push(await request.json())
        return HttpResponse.json({}, { status: 201 })
      }),
      http.post('/me/workspaces/:name/up', async ({ request }) => {
        capturedBodies.push(await request.json())
        return HttpResponse.json({ ws_id: 'alice-my-ws', status: 'provisioning' }, { status: 202 })
      }),
    )

    const user = userEvent.setup()
    renderWithProviders(<WorkspaceCreate />)

    await screen.findByText('VSCode Profile')

    await user.type(screen.getByLabelText(/^name$/i), 'my-ws')
    // Aucun profil sélectionné — on soumet directement
    await user.click(screen.getByRole('button', { name: /create workspace/i }))

    await waitFor(() => expect(capturedBodies).toHaveLength(2))
    const [specBody, upBody] = capturedBodies as Array<{ profile?: unknown }>
    expect(specBody.profile).toBeNull()
    expect(upBody.profile).toBeNull()
  })
})
