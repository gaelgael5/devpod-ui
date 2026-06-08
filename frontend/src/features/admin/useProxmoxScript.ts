import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiFetch, apiFetchJson } from '@/shared/api/client'

export interface ScriptOption {
  value: string
  label: string
}

export interface ScriptArg {
  arg: string
  label_fr: string
  label_en: string
  description_fr?: string
  description_en?: string
  type: 'integer' | 'string' | 'select'
  required?: boolean
  default?: string | number
  min?: number
  max?: number
  pattern?: string
  options?: ScriptOption[]
  option_script?: string
}

export interface ScriptSpec {
  args: ScriptArg[]
  commands: string[]
  tags?: string[]
}

export function useScriptSpec(nodeName: string | null) {
  return useQuery<ScriptSpec>({
    queryKey: ['admin', 'proxmox', nodeName, 'script'],
    queryFn: () => apiFetchJson<ScriptSpec>(`/admin/proxmox/${nodeName}/script`),
    enabled: nodeName != null,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export interface ExecuteState {
  logs: string
  running: boolean
  done: boolean
  error: string | null
}

export function useExecuteScript() {
  const [state, setState] = useState<ExecuteState>({
    logs: '',
    running: false,
    done: false,
    error: null,
  })

  const reset = useCallback(() => {
    setState({ logs: '', running: false, done: false, error: null })
  }, [])

  const execute = useCallback(async (nodeName: string, args: Record<string, string>) => {
    setState({ logs: '', running: true, done: false, error: null })
    try {
      const res = await apiFetch(`/admin/proxmox/${nodeName}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ args }),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let accum = ''
      while (true) {
        const { done: streamDone, value } = await reader.read()
        if (streamDone) break
        accum += decoder.decode(value, { stream: true })
        const snap = accum
        setState(s => ({ ...s, logs: snap }))
      }
      setState(s => ({ ...s, logs: accum, running: false, done: true }))
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setState(s => ({ ...s, error: msg, running: false, done: true }))
    }
  }, [])

  return { ...state, execute, reset }
}

/** Extrait la dernière ligne non-vide des logs et tente un parse JSON. */
export function extractLastJson(logs: string): Record<string, unknown> | null {
  const lines = logs.split('\n').map(l => l.trim()).filter(Boolean)
  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i].startsWith('{')) {
      try {
        return JSON.parse(lines[i]) as Record<string, unknown>
      } catch {
        // pas JSON valide, continuer vers le haut
      }
    }
  }
  return null
}
