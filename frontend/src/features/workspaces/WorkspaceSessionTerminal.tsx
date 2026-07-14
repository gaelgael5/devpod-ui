import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RotateCw } from 'lucide-react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { Button } from '@/components/ui/button'
import '@xterm/xterm/css/xterm.css'

interface Props {
  wsName: string
  session: string
}

export default function WorkspaceSessionTerminal({ wsName, session }: Props) {
  const { t } = useTranslation()
  const termRef = useRef<HTMLDivElement>(null)
  // La WS peut tomber (veille, réseau, redéploiement du portail). On affiche
  // alors un overlay de reconnexion : le tmux backend survit, une nouvelle
  // connexion s'y rattache via ?session= (évite le F5 qui perd le scrollback).
  const [disconnected, setDisconnected] = useState(false)
  const [epoch, setEpoch] = useState(0)
  // t change d'identité à chaque changement de langue ; le lire via une ref (au
  // lieu de le mettre en dépendance de l'effet) évite de reconstruire le
  // terminal + WebSocket — et donc de couper la connexion en cours — quand
  // l'utilisateur change juste la langue de l'UI (bug 043).
  const tRef = useRef(t)
  useLayoutEffect(() => {
    tRef.current = t
  })

  useEffect(() => {
    // true = démontage/reconnexion volontaire → ne pas afficher l'overlay.
    let intentional = false
    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: "'Courier New', monospace",
      fontSize: 13,
      theme: { background: '#0d0d1a', foreground: '#e0e0ff', cursor: '#e0e0ff' },
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)

    if (termRef.current) {
      terminal.open(termRef.current)
      requestAnimationFrame(() => { fitAddon.fit(); terminal.focus() })
    }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(
      `${proto}//${window.location.host}/me/workspaces/${encodeURIComponent(wsName)}/ssh` +
      `?session=${encodeURIComponent(session)}`
    )
    ws.binaryType = 'arraybuffer'

    const sendResize = (cols: number, rows: number) => {
      if (ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'resize', cols, rows }))
    }

    // Envoie la taille courante dès l'ouverture (cas où fit() a tourné avant onopen)
    ws.onopen = () => sendResize(terminal.cols, terminal.rows)

    const encoder = new TextEncoder()
    const dataDisposable = terminal.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(data))
    })
    // Propagation des changements de taille au PTY backend → SIGWINCH → tmux redraw
    const resizeDisposable = terminal.onResize(({ cols, rows }) => sendResize(cols, rows))

    ws.onmessage = (e) => {
      const data = e.data instanceof ArrayBuffer ? new Uint8Array(e.data) : e.data
      terminal.write(data)
    }
    ws.onclose = () => {
      terminal.write(tRef.current('admin.sshTerminal.connClosed'))
      if (!intentional) setDisconnected(true)
    }
    ws.onerror = () => terminal.write(tRef.current('admin.sshTerminal.connError'))

    const onResize = () => fitAddon.fit()
    window.addEventListener('resize', onResize)
    const ro = new ResizeObserver(() => fitAddon.fit())
    if (termRef.current) ro.observe(termRef.current)

    return () => {
      intentional = true
      window.removeEventListener('resize', onResize)
      ro.disconnect()
      dataDisposable.dispose()
      resizeDisposable.dispose()
      ws.close()
      terminal.dispose()
    }
  }, [wsName, session, epoch])

  return (
    <div className="absolute inset-0 bg-[#0d0d1a]">
      <div ref={termRef} className="absolute inset-0" />
      {disconnected && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/60 backdrop-blur-sm">
          <p className="text-sm text-white/80">{t('workspaces.terminals.disconnected')}</p>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => { setDisconnected(false); setEpoch((e) => e + 1) }}
          >
            <RotateCw className="mr-1 h-3.5 w-3.5" />
            {t('workspaces.terminals.reconnect')}
          </Button>
        </div>
      )}
    </div>
  )
}
