import { describe, expect, it, beforeEach } from 'vitest'
import { useUserStore } from './user'

describe('useUserStore', () => {
  beforeEach(() => {
    useUserStore.setState({ user: null })
  })

  it('démarre sans user', () => {
    expect(useUserStore.getState().user).toBeNull()
  })

  it('setUser stocke login et roles', () => {
    useUserStore.getState().setUser({ login: 'alice', roles: ['dev'] })
    expect(useUserStore.getState().user?.login).toBe('alice')
    expect(useUserStore.getState().user?.roles).toContain('dev')
  })

  it('clear remet user à null', () => {
    useUserStore.getState().setUser({ login: 'alice', roles: ['dev'] })
    useUserStore.getState().clear()
    expect(useUserStore.getState().user).toBeNull()
  })

  it('isAdmin retourne true si le rôle admin est présent', () => {
    useUserStore.getState().setUser({ login: 'alice', roles: ['dev', 'admin'] })
    expect(useUserStore.getState().isAdmin()).toBe(true)
  })

  it('isAdmin retourne false si seul dev', () => {
    useUserStore.getState().setUser({ login: 'alice', roles: ['dev'] })
    expect(useUserStore.getState().isAdmin()).toBe(false)
  })
})
