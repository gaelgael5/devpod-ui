// Utilitaires (non-composants) de l'éditeur de règle : constantes de style,
// slugification, conversion en-têtes UI ↔ API.

import type { HeaderRow } from './useAutomations'

export const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

export const SELECT_CLS =
  'h-9 w-full rounded-md border border-input bg-background px-2 text-sm ' +
  'ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

export function slugify(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64)
}

export interface HeaderDraft {
  name: string
  value: string
  secretRef: string
  valuePrefix: string
  isSecret: boolean
  required: boolean
  enabled: boolean
}

export function toDrafts(headers: HeaderRow[]): HeaderDraft[] {
  return headers.map((h) => ({
    name: h.name,
    value: h.value ?? '',
    secretRef: h.secret_ref ?? '',
    valuePrefix: h.value_prefix ?? '',
    isSecret: h.secret_ref != null || (h.value == null && !!h.value_prefix),
    required: h.required ?? false,
    enabled: h.enabled ?? true,
  }))
}

export function draftsToRows(drafts: HeaderDraft[]): HeaderRow[] {
  return drafts
    .filter((h) => h.name.trim())
    .map((h) => ({
      name: h.name.trim(),
      value: h.isSecret ? null : h.value || null,
      secret_ref: h.isSecret ? h.secretRef || null : null,
      value_prefix: h.valuePrefix || undefined,
      required: h.required,
      enabled: h.enabled,
    }))
}
