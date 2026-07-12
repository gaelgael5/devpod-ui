const BASE = import.meta.env.VITE_API_URL ?? ''

// Corps d'erreur non-JSON au-delà de cette taille : jamais affiché tel quel côté
// utilisateur (page d'erreur d'un proxy/CDN en amont — Cloudflare, Caddy — ou
// stack trace), remplacé par un message générique borné par le statut HTTP.
const MAX_RAW_ERROR_LENGTH = 300
const HTML_DOCUMENT_RE = /^<(!doctype html|html)/i

/**
 * Message d'erreur affichable depuis une réponse HTTP en échec.
 *
 * `detail` JSON (contrat FastAPI) → utilisé tel quel. Sinon, un corps qui
 * ressemble à un document HTML (page d'erreur d'un proxy en amont, jamais
 * destinée à un humain) ou trop long retombe sur `status`/`statusText`.
 */
function extractErrorMessage(status: number, statusText: string, rawBody: string): string {
  const trimmed = rawBody.trim()
  const fallback = statusText || `HTTP ${status}`
  if (!trimmed) return fallback
  try {
    const json = JSON.parse(trimmed)
    if (typeof json.detail === 'string') return json.detail
  } catch {
    // pas du JSON — traité ci-dessous
  }
  if (HTML_DOCUMENT_RE.test(trimmed)) return fallback
  return trimmed.length > MAX_RAW_ERROR_LENGTH ? `${trimmed.slice(0, MAX_RAW_ERROR_LENGTH)}…` : trimmed
}

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

async function throwApiError(res: Response): Promise<never> {
  const text = await res.text().catch(() => '')
  throw new ApiError(res.status, extractErrorMessage(res.status, res.statusText, text))
}

export async function apiFetchVoid(path: string, init?: RequestInit): Promise<void> {
  const res = await apiFetch(path, init)
  if (!res.ok) await throwApiError(res)
  // 204 No Content — pas de corps à désérialiser
}

export async function apiFetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) await throwApiError(res)
  // res.json() returns unknown; caller is responsible for type correctness (no runtime schema validation)
  return res.json() as Promise<T>
}
