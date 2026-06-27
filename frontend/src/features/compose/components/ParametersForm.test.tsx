import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ParametersForm from './ParametersForm'
import type { ComposeParam } from '../api/types'

const params: ComposeParam[] = [
  { key: 'WEB_PORT', label: 'Port', type: 'port', required: true },
  { key: 'MODE', label: 'Mode', type: 'enum', required: false, options: ['a', 'b'] },
  { key: 'TOKEN', label: 'Token', type: 'secret', required: true },
]

describe('ParametersForm', () => {
  it('renders a widget per param and emits onChange', () => {
    const onChange = vi.fn()
    render(<ParametersForm parameters={params} values={{}} onChange={onChange} />)
    expect(screen.getByLabelText(/Port/)).toBeInTheDocument()
    const port = screen.getByLabelText(/Port/)
    fireEvent.change(port, { target: { value: '3000' } })
    expect(onChange).toHaveBeenCalledWith('WEB_PORT', '3000')
  })
  it('secret field hints a vault reference', () => {
    render(<ParametersForm parameters={params} values={{}} onChange={() => {}} />)
    expect(screen.getByPlaceholderText(/vault:\/\//)).toBeInTheDocument()
  })
})
