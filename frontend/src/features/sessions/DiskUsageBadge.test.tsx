/**
 * Ratio d'occupation disque affiché dans la fenêtre sessions.
 *
 * Le seuil d'alerte est décidé par le SERVEUR (`warn`) : l'UI ne le recalcule
 * pas, sinon les deux divergent le jour où il change. Ces tests verrouillent ce
 * contrat, et le formatage des octets — afficher « 0 o libres » sur une valeur
 * inconnue ferait croire à un disque plein.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import DiskUsageBadge from './DiskUsageBadge'
import { formatBytes } from './formatBytes'
import type { DiskUsage } from './useSessions'

function disk(over: Partial<DiskUsage> = {}): DiskUsage {
  return {
    total_bytes: 46036664320,
    used_bytes: 23018332160,
    avail_bytes: 23018332160,
    used_pct: 50,
    warn: false,
    measured_at: '2026-08-17T05:00:00Z',
    ...over,
  }
}

function show(d: DiskUsage) {
  return render(
    <I18nextProvider i18n={i18n}>
      <DiskUsageBadge disk={d} />
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

describe('DiskUsageBadge', () => {
  it('affiche le pourcentage et l’espace libre', () => {
    show(disk())
    expect(screen.getByTestId('disk-usage')).toHaveTextContent('50%')
    expect(screen.getByTestId('disk-usage')).toHaveTextContent('21 Go')
  })

  it('signale visuellement l’alerte décidée par le serveur', () => {
    show(disk({ used_pct: 96, warn: true, avail_bytes: 0 }))
    const badge = screen.getByTestId('disk-usage')
    expect(badge).toHaveTextContent('96%')
    expect(badge.className).toContain('destructive')
  })

  it('ne passe PAS en alerte sur un pourcentage élevé si le serveur dit non', () => {
    // Le seuil appartient au serveur : 89 % sans warn reste un état « tendu ».
    const badge = show(disk({ used_pct: 89, warn: false })).getByTestId('disk-usage')
    expect(badge.className).not.toContain('destructive')
    expect(badge.className).toContain('amber')
  })

  it('reste neutre en dessous de la zone de tension', () => {
    const badge = show(disk({ used_pct: 40 })).getByTestId('disk-usage')
    expect(badge.className).not.toContain('destructive')
    expect(badge.className).not.toContain('amber')
  })
})
