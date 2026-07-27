// Même contrainte que le backend (routes/workspace_sessions.py::_SESSION_NAME_RE) :
// un nom de session non conforme casse le chemin /sessions/{name} (bug 044).
export const SESSION_NAME_RE = /^[a-z0-9][a-z0-9-]{0,29}$/

export function computeNextName(sessions: string[], wsName: string): string {
  const existing = new Set(sessions)
  for (let i = 1; i <= 100; i++) {
    const n = `${wsName}${i}`
    if (!existing.has(n)) return n
  }
  return `${wsName}${sessions.length + 1}`
}
