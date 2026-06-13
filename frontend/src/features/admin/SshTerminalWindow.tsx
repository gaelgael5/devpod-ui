import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import type { HostConfig } from './useHosts'

interface Props {
  host: HostConfig
  onClose: () => void
}

export default function SshTerminalWindow({ host, onClose }: Props) {
  const { t } = useTranslation()
  const termRef = useRef<HTMLDivElement>(null)
  const posRef = useRef({ x: Math.max(0, window.innerWidth - 640), y: 80 })
  const winRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const dragOrigin = useRef({ mx: 0, my: 0, wx: 0, wy: 0 })
  const wsRef = useRef<WebSocket | null>(null)

  // ── Terminal + WebSocket ───────────────────────────────────────────────────
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
      fitAddon.fit()
      terminal.focus()
    }

    // Redimensionnement : window resize + resize handle CSS
    const onResize = () => fitAddon.fit()
    window.addEventListener('resize', onResize)

    const ro = new ResizeObserver(() => fitAddon.fit())
    if (winRef.current) ro.observe(winRef.current)

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(
      `${proto}//${window.location.host}/admin/hosts/${encodeURIComponent(host.name)}/ssh`
    )
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    const encoder = new TextEncoder()
    const dataDisposable = terminal.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(encoder.encode(data))
    })

    ws.onmessage = (e) => {
      const data = e.data instanceof ArrayBuffer ? new Uint8Array(e.data) : e.data
      terminal.write(data)
    }
    ws.onclose = () => terminal.write(t('admin.sshTerminal.connClosed'))
    ws.onerror = () => terminal.write(t('admin.sshTerminal.connError'))

    return () => {
      window.removeEventListener('resize', onResize)
      ro.disconnect()
      dataDisposable.dispose()
      ws.close()
      terminal.dispose()
      wsRef.current = null
    }
  }, [host.name, t])

  // ── Drag ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragging.current || !winRef.current) return
      posRef.current = {
        x: dragOrigin.current.wx + e.clientX - dragOrigin.current.mx,
        y: dragOrigin.current.wy + e.clientY - dragOrigin.current.my,
      }
      winRef.current.style.left = `${posRef.current.x}px`
      winRef.current.style.top = `${posRef.current.y}px`
    }
    function onUp() {
      dragging.current = false
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
  }, [])

  function handleHeaderMouseDown(e: React.MouseEvent) {
    if ((e.target as HTMLElement).tagName === 'BUTTON') return
    dragging.current = true
    dragOrigin.current = {
      mx: e.clientX,
      my: e.clientY,
      wx: posRef.current.x,
      wy: posRef.current.y,
    }
    e.preventDefault()
  }

  function handleClose() {
    wsRef.current?.close()
    onClose()
  }

  const window_ = (
    <div
      ref={winRef}
      style={{
        position: 'fixed',
        left: posRef.current.x,
        top: posRef.current.y,
        width: 600,
        height: 440,
        minWidth: 360,
        minHeight: 240,
        zIndex: 9999,
        borderRadius: 8,
        overflow: 'hidden',
        boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
        display: 'flex',
        flexDirection: 'column',
        resize: 'both',
      }}
    >
      {/* Header draggable */}
      <div
        onMouseDown={handleHeaderMouseDown}
        style={{
          background: '#2d2d3f',
          padding: '8px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'grab',
          userSelect: 'none',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 12, color: '#a0a0c0', fontFamily: 'monospace' }}>
          ⚡ {host.address ?? '(no address)'}
        </span>
        <button
          onClick={handleClose}
          aria-label={t('admin.sshTerminal.closeLabel')}
          style={{
            width: 13,
            height: 13,
            borderRadius: '50%',
            background: '#ef4444',
            border: 'none',
            cursor: 'pointer',
            display: 'block',
          }}
        />
      </div>

      {/* Terminal — prend tout l'espace restant */}
      <div
        ref={termRef}
        style={{ flex: 1, minHeight: 0, background: '#0d0d1a', padding: '4px 2px' }}
      />
    </div>
  )

  return createPortal(window_, document.body)
}
