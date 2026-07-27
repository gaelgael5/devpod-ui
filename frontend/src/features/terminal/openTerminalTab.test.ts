import { describe, it, expect, vi } from 'vitest'
import { openTerminalTab } from './openTerminalTab'

describe('openTerminalTab', () => {
  it('ouvre /terminal en nouvel onglet avec ws et title encodés', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    openTerminalTab('/admin/hosts/host-dev-01/ssh', 'host-dev-01')
    expect(open).toHaveBeenCalledWith(
      '/terminal?ws=%2Fadmin%2Fhosts%2Fhost-dev-01%2Fssh&title=host-dev-01',
      '_blank',
      'noopener',
    )
    open.mockRestore()
  })

  it('encode la query du chemin workspace (ssh_test)', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    openTerminalTab('/me/workspaces/ws1/ssh?ssh_test=host-x', 'test1')
    expect(open).toHaveBeenCalledWith(
      '/terminal?ws=%2Fme%2Fworkspaces%2Fws1%2Fssh%3Fssh_test%3Dhost-x&title=test1',
      '_blank',
      'noopener',
    )
    open.mockRestore()
  })
})
