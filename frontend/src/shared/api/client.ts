const BASE = import.meta.env.VITE_API_URL ?? ''

export class ApiError extends Error {
  // Champ déclaré explicitement (pas en parameter property) : `erasableSyntaxOnly`
  // interdit les parameter properties dans le constructeur.
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, { credentials: 'include', ...init })
  if (res.status === 401) {
    window.location.href = '/auth/login'
    throw new ApiError(401, 'Unauthenticated')
  }
  return res
}

export async function apiFetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let message = text || res.statusText
    try {
      const json = JSON.parse(text)
      if (typeof json.detail === 'string') message = json.detail
    } catch {
      // pas du JSON — on garde le texte brut
    }
    throw new ApiError(res.status, message)
  }
  // res.json() returns unknown; caller is responsible for type correctness (no runtime schema validation)
  return res.json() as Promise<T>
}
