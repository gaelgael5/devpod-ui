/**
 * Ouvre un terminal SSH dans un **nouvel onglet** (cohérent avec les sessions de
 * workspace). `wsPath` est le chemin WebSocket same-origin (ex.
 * `/me/workspaces/x/ssh?session=y` ou `/admin/hosts/h/ssh`) ; il est passé à la
 * page plein écran `/terminal` qui s'y connecte.
 */
export function openTerminalTab(wsPath: string, title: string): void {
  const url =
    `/terminal?ws=${encodeURIComponent(wsPath)}&title=${encodeURIComponent(title)}`
  window.open(url, '_blank', 'noopener')
}
