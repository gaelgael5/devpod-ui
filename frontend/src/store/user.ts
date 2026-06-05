import { create } from 'zustand'

export interface UserInfo {
  login: string
  roles: string[]
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
  isAdmin: () => get().user?.roles.includes('admin') ?? false,
}))
