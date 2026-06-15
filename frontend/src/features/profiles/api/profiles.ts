import { apiFetch, apiFetchJson } from '@/shared/api/client'

export type Scope = 'shared' | 'user'

export interface ProfileBody {
  name: string
  description: string
  extensions: string[]
  settings: Record<string, unknown>
}

export interface ProfileSummary {
  slug: string
  scope: Scope
  name: string
  description: string
  extension_count: number
  editable: boolean
}

export interface Profile extends ProfileBody {
  slug: string
  scope: Scope
}

export function listProfiles(): Promise<ProfileSummary[]> {
  return apiFetchJson<ProfileSummary[]>('/profiles')
}

export function getProfile(scope: Scope, slug: string): Promise<Profile> {
  return apiFetchJson<Profile>(`/profiles/${scope}/${encodeURIComponent(slug)}`)
}

export function createProfile(body: ProfileBody): Promise<Profile> {
  return apiFetchJson<Profile>('/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function updateProfile(slug: string, body: ProfileBody): Promise<Profile> {
  return apiFetchJson<Profile>(`/profiles/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function deleteProfile(slug: string): Promise<void> {
  await apiFetch(`/profiles/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}

export function forkProfile(slug: string): Promise<Profile> {
  return apiFetchJson<Profile>(`/profiles/shared/${encodeURIComponent(slug)}/fork`, {
    method: 'POST',
  })
}

// ── Admin ────────────────────────────────────────────────────────────────────

export function listSharedProfiles(): Promise<ProfileSummary[]> {
  return apiFetchJson<ProfileSummary[]>('/admin/profiles')
}

export function createSharedProfile(body: ProfileBody): Promise<Profile> {
  return apiFetchJson<Profile>('/admin/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function updateSharedProfile(slug: string, body: ProfileBody): Promise<Profile> {
  return apiFetchJson<Profile>(`/admin/profiles/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function deleteSharedProfile(slug: string): Promise<void> {
  await apiFetch(`/admin/profiles/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}
