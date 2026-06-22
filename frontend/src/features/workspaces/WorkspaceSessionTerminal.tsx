import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

interface Props {
  wsName: string
  session: string
}

export default function WorkspaceSessionTerminal({ wsName, session }: Props) {
  const { t } = useTranslation()
  const termRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
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
    ws.onclose = () => terminal.write(t('admin.sshTerminal.connClosed'))
    ws.onerror = () => terminal.write(t('admin.sshTerminal.connError'))

    const onResize = () => fitAddon.fit()
    window.addEventListener('resize', onResize)
    const ro = new ResizeObserver(() => fitAddon.fit())
    if (termRef.current) ro.observe(termRef.current)

    return () => {
      window.removeEventListener('resize', onResize)
      ro.disconnect()
      dataDisposable.dispose()
      resizeDisposable.dispose()
      ws.close()
      terminal.dispose()
    }
  }, [wsName, session, t])

  return <div ref={termRef} className="absolute inset-0 bg-[#0d0d1a]" />
}
