import type { WorkspaceSpec } from './types'

/** Partition stable : les workspaces arrêtés passent en fin de groupe, ordre inchangé sinon. */
export function stoppedLast(
  workspaces: WorkspaceSpec[],
  statusOf: (name: string) => string | undefined,
): WorkspaceSpec[] {
  return [
    ...workspaces.filter((w) => statusOf(w.name) !== 'stopped'),
    ...workspaces.filter((w) => statusOf(w.name) === 'stopped'),
  ]
}
