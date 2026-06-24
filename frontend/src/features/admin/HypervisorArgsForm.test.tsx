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
