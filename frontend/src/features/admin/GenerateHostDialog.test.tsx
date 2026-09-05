/**
 * Generation d'un host : hyperviseur → profil → ce qui manque seulement.
 *
 * Le profil fige les parametres. Reafficher ceux qu'il renseigne n'apporterait
 * rien ; seuls les args obligatoires qu'il ne couvre pas demandent une decision.
 */
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderWithProviders } from '@/test/renderWithProviders'
import GenerateHostDialog from './GenerateHostDialog'

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

const SPEC = {
  args: [
    {
      arg: 'NEW_VMID',
      identifier: true,
      required: true,
      label_fr: 'VMID',
      label_en: 'VMID',
      type: 'select',
      options: [{ value: 'auto', label: 'auto' }],
    },
    {
      arg: 'NODE_NAME',
      required: true,
      label_fr: 'Nom DNS',
      label_en: 'DNS name',
      type: 'string',
      default: 'host-dev-01',
    },
    { arg: 'CI_USER', label_fr: 'Utilisateur', label_en: 'User', type: 'string', default: 'debian' },
    {
      arg: 'SSH_KEY',
      required: true,
      label_fr: 'Clé SSH',
      label_en: 'SSH key',
      type: 'string',
    },
  ],
  commands: ['echo {NODE_NAME}'],
}

const PROFIL_COMPLET = {
  slug: 'dev-standard',
  label: 'Dev standard',
  machine_type: 'workspaces',
  hypervisor_type: 'proxmox',
  params: { NODE_NAME: 'host-dev-{count++}', CI_USER: 'debian', SSH_KEY: 'ssh-ed25519 AAA' },
  recipes: [],
  services: [],
}

function renderDialog(profils: unknown[]) {
  server.use(
    http.get('/admin/hypervisors', () =>
      HttpResponse.json([
        { name: 'pve1', address: '192.168.10.41', hypervisor_type: 'proxmox' },
      ]),
    ),
    http.get('/admin/hypervisors/:name/script', () => HttpResponse.json(SPEC)),
    http.get('/admin/machine-profiles', () => HttpResponse.json(profils)),
  )
  renderWithProviders(
    <GenerateHostDialog open onClose={vi.fn()} onGenerated={vi.fn()} />,
  )
}

async function choisirHyperviseur() {
  await userEvent.click(await screen.findByText('pve1'))
}

describe('GenerateHostDialog — arbre des profils', () => {
  it('groupe les profils par type de machine', async () => {
    renderDialog([PROFIL_COMPLET])
    await choisirHyperviseur()

    expect(await screen.findByText('Dev standard')).toBeInTheDocument()
    // Les quatre groupes structurent l'ecran, meme vides.
    for (const groupe of [
      /^Workspaces$/,
      /Machine de test|Test machine/,
      /Ressources partag|Shared resources/,
      /^Autres$|^Other$/,
    ]) {
      expect(screen.getAllByText(groupe).length).toBeGreaterThan(0)
    }
  })

  it('n’expose pas les profils d’un autre type d’hyperviseur', async () => {
    renderDialog([PROFIL_COMPLET, { ...PROFIL_COMPLET, slug: 'autre', label: 'Profil libvirt', hypervisor_type: 'libvirt' }])
    await choisirHyperviseur()

    await screen.findByText('Dev standard')
    expect(screen.queryByText('Profil libvirt')).toBeNull()
  })

  it('ne demande que les args obligatoires que le profil ne couvre pas', async () => {
    const incomplet = { ...PROFIL_COMPLET, params: { NODE_NAME: 'host-dev-{count++}' } }
    renderDialog([incomplet])
    await choisirHyperviseur()

    await userEvent.click(await screen.findByText('Dev standard'))

    // SSH_KEY est obligatoire et non renseigne → demande.
    expect(await screen.findByText(/clé ssh|ssh key/i)).toBeInTheDocument()
    // NODE_NAME et CI_USER sont figes par le profil / la spec → pas reaffiches.
    expect(screen.queryByText(/nom dns|dns name/i)).toBeNull()
    expect(screen.queryByText(/utilisateur|^user$/i)).toBeNull()
  })

  it('lance directement quand le profil ne laisse rien a saisir', async () => {
    renderDialog([PROFIL_COMPLET])
    await choisirHyperviseur()

    await userEvent.click(await screen.findByText('Dev standard'))

    // On saute l'ecran de parametres : plus de bouton « Exécuter » a cliquer.
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /exécuter|execute/i })).toBeNull(),
    )
  })

  it('garde une porte de sortie sans profil', async () => {
    renderDialog([])
    await choisirHyperviseur()

    await userEvent.click(await screen.findByText(/créer sans profil|create without a profile/i))

    // Formulaire complet : les args figes par un profil sont la.
    expect(await screen.findByText(/nom dns|dns name/i)).toBeInTheDocument()
  })
})
