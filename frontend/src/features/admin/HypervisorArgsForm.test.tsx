import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import HypervisorArgsForm from './HypervisorArgsForm'
import type { ScriptArgOrSub } from './useProxmoxScript'

const ARGS: ScriptArgOrSub[] = [
  {
    arg: 'NEW_VMID',
    identifier: true,
    label_fr: 'VMID',
    label_en: 'VMID',
    type: 'select',
    options: [{ value: 'auto', label: 'auto' }],
  },
  { arg: 'CI_USER', label_fr: 'CloudInitUser', label_en: 'CloudInitUser', type: 'string' },
  {
    type: 'sub',
    label_fr: 'Network',
    label_en: 'Network',
    args: [{ arg: 'IP_CIDR', label_fr: 'IPCidr', label_en: 'IPCidr', type: 'string' }],
  },
]

beforeAll(() => {
  Element.prototype.hasPointerCapture = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

describe('HypervisorArgsForm', () => {
  it('exclut l\'arg identifier quand excludeIdentifier', () => {
    renderWithProviders(
      <HypervisorArgsForm args={ARGS} values={{}} onChange={() => {}} excludeIdentifier />,
    )
    expect(screen.getByText('CloudInitUser')).toBeInTheDocument()
    expect(screen.getByText('IPCidr')).toBeInTheDocument() // arg dans un groupe sub
    expect(screen.queryByText('VMID')).toBeNull() // identifier masqué
  })

  it('affiche l\'identifier sans excludeIdentifier', () => {
    renderWithProviders(<HypervisorArgsForm args={ARGS} values={{}} onChange={() => {}} />)
    expect(screen.getByText('VMID')).toBeInTheDocument()
  })

  it('remonte les saisies via onChange', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithProviders(
      <HypervisorArgsForm args={ARGS} values={{}} onChange={onChange} excludeIdentifier />,
    )
    await user.type(screen.getByLabelText('CloudInitUser'), 'x')
    expect(onChange).toHaveBeenCalledWith('CI_USER', 'x')
  })
})

describe('HypervisorArgsForm — rappel des variables de templating', () => {
  /**
   * Le rappel se lit AU CHAMP : c'est au moment de saisir « host-test-{count++} »
   * qu'on a besoin de savoir que la variable existe, pas dans un bandeau en tete
   * de formulaire.
   */
  it('affiche les variables a cote de chaque libelle quand templating est actif', () => {
    renderWithProviders(
      <HypervisorArgsForm args={ARGS} values={{}} onChange={() => {}} templating />,
    )

    // Un rappel par champ textuel (CI_USER, IP_CIDR) — pas sur le select VMID.
    const rappels = screen.getAllByText(/\{count\+\+\}/)
    expect(rappels).toHaveLength(2)
  })

  it('ne dit rien sans templating — a la creation les valeurs sont deja resolues', () => {
    renderWithProviders(<HypervisorArgsForm args={ARGS} values={{}} onChange={() => {}} />)

    expect(screen.queryByText(/\{count\+\+\}/)).toBeNull()
  })
})
