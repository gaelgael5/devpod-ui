import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import YamlEditor from './YamlEditor'

describe('YamlEditor', () => {
  it('renders value and emits onChange', () => {
    const onChange = vi.fn()
    const { container } = render(<YamlEditor value="services: {}" onChange={onChange} />)
    const ta = container.querySelector('textarea')!
    fireEvent.change(ta, { target: { value: 'services:\n  a: {}' } })
    expect(onChange).toHaveBeenCalledWith('services:\n  a: {}')
  })
})
