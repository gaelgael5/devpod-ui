/**
 * Disque, mémoire et charge CPU affichés sous le nom de la machine.
 *
 * Deux contrats verrouillés ici :
 * - le seuil d'alerte disque appartient au SERVEUR (`warn`) ; l'UI ne le
 *   recalcule pas, sinon les deux divergent le jour où il change ;
 * - les trois mesures sont INDÉPENDAMMENT optionnelles : une machine dont
 *   /proc/meminfo est illisible doit quand même afficher son disque.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import ResourceMetrics from './ResourceMetrics'
import { formatBytes } from './formatBytes'
import type { CpuUsage, DiskUsage, MemoryUsage } from './useSessions'

const DISK: DiskUsage = {
  total_bytes: 46036664320,
  used_bytes: 23018332160,
  avail_bytes: 23018332160,
  used_pct: 50,
  warn: false,
  measured_at: '2026-08-17T05:00:00Z',
}
const MEM: MemoryUsage = { total_bytes: 16718102528, used_bytes: 6613417984, used_pct: 40 }
const CPU: CpuUsage = { used_pct: 25, cores: 8 }

function show(props: { disk?: DiskUsage; memory?: MemoryUsage; cpu?: CpuUsage }) {
  return render(
    <I18nextProvider i18n={i18n}>
      <ResourceMetrics {...props} />
    </I18nextProvider>,
  )
}

describe('formatBytes', () => {
  it('rend les octets lisibles', () => {
    expect(formatBytes(0)).toBe('0 o')
    expect(formatBytes(1024)).toBe('1.0 Ko')
    expect(formatBytes(46036664320)).toBe('43 Go')
  })

  it('ne fabrique jamais une valeur pour un inconnu', () => {
    // « 0 o » sur une valeur absente ferait croire à un disque plein.
    expect(formatBytes(null)).toBe('?')
    expect(formatBytes(undefined)).toBe('?')
  })
})

describe('ResourceMetrics', () => {
  it('affiche les trois mesures', () => {
    show({ disk: DISK, memory: MEM, cpu: CPU })
    const block = screen.getByTestId('resource-metrics')
    expect(block).toHaveTextContent('50%')
    expect(block).toHaveTextContent('40%')
    expect(block).toHaveTextContent('25%')
  })

  it('affiche le disque même sans mémoire ni CPU', () => {
    // Un noyau sans /proc/meminfo exploitable ne doit pas faire perdre le
    // disque, qui porte l'alerte.
    show({ disk: DISK })
    expect(screen.getByTestId('resource-metrics')).toHaveTextContent('50%')
    expect(screen.queryByTestId('metric-memory')).not.toBeInTheDocument()
  })

  it('ne rend rien pour une machine jamais sondée', () => {
    show({})
    expect(screen.queryByTestId('resource-metrics')).not.toBeInTheDocument()
  })

  it('signale l’alerte disque décidée par le serveur', () => {
    show({ disk: { ...DISK, used_pct: 96, warn: true, avail_bytes: 0 } })
    expect(screen.getByTestId('metric-disk').className).toContain('destructive')
  })

  it('ne passe PAS en alerte sur un disque élevé si le serveur dit non', () => {
    // Le seuil appartient au serveur : 89 % sans `warn` reste « tendu ».
    const el = show({ disk: { ...DISK, used_pct: 89, warn: false } }).getByTestId('metric-disk')
    expect(el.className).not.toContain('destructive')
    expect(el.className).toContain('amber')
  })
})
