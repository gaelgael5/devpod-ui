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
    useUserStore.getState().setUser({ login: 'alice', roles: ['dev'], is_admin: false })
    expect(useUserStore.getState().user?.login).toBe('alice')
    expect(useUserStore.getState().user?.roles).toContain('dev')
  })

  it('clear remet user à null', () => {
    useUserStore.getState().setUser({ login: 'alice', roles: ['dev'], is_admin: false })
    useUserStore.getState().clear()
    expect(useUserStore.getState().user).toBeNull()
  })

  it("isAdmin reflète le flag is_admin calculé par le backend (le nom du rôle admin est une config serveur, ex. yoops-admin)", () => {
    useUserStore.getState().setUser({ login: 'alice', roles: ['yoops-admin'], is_admin: true })
    expect(useUserStore.getState().isAdmin()).toBe(true)
  })

  it('isAdmin retourne false si is_admin est false, quels que soient les rôles', () => {
    useUserStore.getState().setUser({ login: 'alice', roles: ['dev', 'admin'], is_admin: false })
    expect(useUserStore.getState().isAdmin()).toBe(false)
  })
})
