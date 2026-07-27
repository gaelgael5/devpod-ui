import { create } from 'zustand'

export interface UserInfo {
  login: string
  roles: string[]
  /** Calculé par le backend (GET /me) : le nom du rôle admin est une config
   serveur (oidc_admin_role) que le frontend ne doit pas connaître. */
  is_admin: boolean
}

interface UserStore {
  user: UserInfo | null
  setUser: (user: UserInfo) => void
  clear: () => void
  isAdmin: () => boolean
}

export const useUserStore = create<UserStore>()((set, get) => ({
  user: null,
  setUser: (user) => set({ user }),
  clear: () => set({ user: null }),
  isAdmin: () => get().user?.is_admin ?? false,
}))
