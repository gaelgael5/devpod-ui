import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { renderWithProviders } from '@/test/renderWithProviders'
import TerminalKeybar from './TerminalKeybar'

// Toaster non monté dans renderWithProviders — on espionne les appels.
vi.mock('sonner', async () => {
  const actual = await vi.importActual<typeof import('sonner')>('sonner')
  return {
    ...actual,
    toast: { ...actual.toast, success: vi.fn(), error: vi.fn(), info: vi.fn() },
  }
})

// navigator.clipboard n'a qu'un getter en jsdom — le redéfinir (configurable).
function stubClipboard(impl: { readText: () => Promise<string>; writeText: () => Promise<void> | void }) {
  Object.defineProperty(navigator, 'clipboard', { value: impl, configurable: true })
}

beforeEach(() => {
  vi.mocked(toast.success).mockClear()
  vi.mocked(toast.error).mockClear()
  vi.mocked(toast.info).mockClear()
})

describe('TerminalKeybar', () => {
  it('envoie \\x1b (Échap) et \\x03 (Interrompre) dans le stdin', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    renderWithProviders(<TerminalKeybar onSend={onSend} onPaste={vi.fn()} getSelection={() => ''} />)

    await user.click(screen.getByRole('button', { name: /échap|esc/i }))
    expect(onSend).toHaveBeenCalledWith('\x1b')

    await user.click(screen.getByRole('button', { name: /interrompre|interrupt/i }))
    expect(onSend).toHaveBeenCalledWith('\x03')
  })

  it('envoie les séquences ANSI des flèches dans le stdin', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    renderWithProviders(<TerminalKeybar onSend={onSend} onPaste={vi.fn()} getSelection={() => ''} />)

    await user.click(screen.getByRole('button', { name: /flèche haut|arrow up/i }))
    expect(onSend).toHaveBeenCalledWith('\x1b[A')
    await user.click(screen.getByRole('button', { name: /flèche bas|arrow down/i }))
    expect(onSend).toHaveBeenCalledWith('\x1b[B')
    await user.click(screen.getByRole('button', { name: /flèche droite|arrow right/i }))
    expect(onSend).toHaveBeenCalledWith('\x1b[C')
    await user.click(screen.getByRole('button', { name: /flèche gauche|arrow left/i }))
    expect(onSend).toHaveBeenCalledWith('\x1b[D')
  })

  it('n’expose plus de bouton Tab', () => {
    // Retire de la barre : au tactile, la double tape apres la fin de la ligne
    // envoie Tab, et la place gagnee compte sur un ecran de telephone.
    renderWithProviders(
      <TerminalKeybar onSend={vi.fn()} onPaste={vi.fn()} getSelection={() => ''} />,
    )

    expect(screen.queryByRole('button', { name: /^tab$/i })).toBeNull()
  })

  it('confie le presse-papier au collage de xterm, pas au stdin brut', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    const onPaste = vi.fn()
    stubClipboard({ readText: vi.fn().mockResolvedValue('salut'), writeText: vi.fn() })
    renderWithProviders(
      <TerminalKeybar onSend={onSend} onPaste={onPaste} getSelection={() => ''} />,
    )

    await user.click(screen.getByRole('button', { name: /coller|paste/i }))

    // Écrit brut dans la WS, le texte échapperait à la normalisation des sauts
    // de ligne et aux marqueurs de « bracketed paste » : un TUI le recevrait
    // comme une rafale de frappes et le rendrait abîmé.
    await waitFor(() => expect(onPaste).toHaveBeenCalledWith('salut'))
    expect(onSend).not.toHaveBeenCalled()
  })

  it('garde un nom accessible sur les boutons sans libelle', () => {
    renderWithProviders(
      <TerminalKeybar
        onSend={vi.fn()}
        onPaste={vi.fn()}
        onSearch={vi.fn()}
        getSelection={() => ''}
      />,
    )

    // Ces boutons n'affichent qu'une icone. Sans aria-label ils n'auraient AUCUN
    // nom : invisibles au lecteur d'ecran, et introuvables par les tests qui les
    // designent par leur nom. (Echap fait exception : il porte « esc » en clair,
    // pour ne pas se confondre avec Entree — voir le describe dedie.)
    for (const nom of [
      /^coller$|^paste$/i,
      /^copier$|^copy$/i,
      /^rechercher$|^search$/i,
      /^interrompre$|^interrupt$/i,
      /^entrée$|^enter$/i,
    ]) {
      const bouton = screen.getByRole('button', { name: nom })
      expect(bouton).toHaveAccessibleName()
      expect(bouton.textContent).toBe('')
    }
  })

  it('ne vole pas le focus au terminal', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <TerminalKeybar onSend={vi.fn()} onPaste={vi.fn()} getSelection={() => ''} />,
    )

    // Sans cela il fallait rendre le focus a xterm apres chaque envoi, ce qui
    // rouvrait le clavier iOS a chaque appui — sur une barre faite justement
    // pour eviter d'avoir a taper.
    for (const nom of [/échap|esc/i, /flèche haut|arrow up/i, /coller|paste/i]) {
      const bouton = screen.getByRole('button', { name: nom })
      const mousedown = new globalThis.MouseEvent('mousedown', {
        bubbles: true,
        cancelable: true,
      })
      bouton.dispatchEvent(mousedown)
      expect(mousedown.defaultPrevented).toBe(true)
    }

    // Le clic doit continuer de partir : seul le deplacement du focus est supprime.
    const onSend = vi.fn()
    renderWithProviders(
      <TerminalKeybar onSend={onSend} onPaste={vi.fn()} getSelection={() => ''} />,
    )
    await user.click(screen.getAllByRole('button', { name: /échap|esc/i })[1])
    expect(onSend).toHaveBeenCalledWith('\x1b')
  })

  it('copie la sélection du terminal vers le presse-papier', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubClipboard({ readText: vi.fn(), writeText })
    renderWithProviders(
      <TerminalKeybar onSend={vi.fn()} onPaste={vi.fn()} getSelection={() => 'ligne sélectionnée'} />
    )

    await user.click(screen.getByRole('button', { name: /copier|copy/i }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('ligne sélectionnée'))
    expect(toast.success).toHaveBeenCalled()
  })

  it('signale une sélection vide sans écrire dans le presse-papier', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn()
    stubClipboard({ readText: vi.fn(), writeText })
    renderWithProviders(<TerminalKeybar onSend={vi.fn()} onPaste={vi.fn()} getSelection={() => ''} />)

    await user.click(screen.getByRole('button', { name: /copier|copy/i }))
    expect(writeText).not.toHaveBeenCalled()
    expect(toast.info).toHaveBeenCalled()
  })
})

describe('TerminalKeybar — bouton clavier', () => {
  function props() {
    return { onSend: vi.fn(), onPaste: vi.fn(), getSelection: () => '' }
  }

  it('masque le bouton quand la bascule n’est pas fournie', () => {
    // Terminal sans clavier a piloter : un bouton inerte tromperait.
    renderWithProviders(<TerminalKeybar {...props()} />)

    expect(screen.queryByRole('button', { name: /^clavier$|^keyboard$/i })).toBeNull()
  })

  it('bascule et reflete l’etat ouvert', async () => {
    const user = userEvent.setup()
    const onToggleKeyboard = vi.fn()
    const { rerender } = renderWithProviders(
      <TerminalKeybar {...props()} onToggleKeyboard={onToggleKeyboard} />,
    )

    const bouton = screen.getByRole('button', { name: /^clavier$|^keyboard$/i })
    expect(bouton).toHaveAttribute('aria-pressed', 'false')
    await user.click(bouton)
    expect(onToggleKeyboard).toHaveBeenCalledTimes(1)

    rerender(<TerminalKeybar {...props()} onToggleKeyboard={onToggleKeyboard} keyboardOpen />)
    expect(screen.getByRole('button', { name: /^clavier$|^keyboard$/i })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})

describe('TerminalKeybar — barre sur une seule ligne', () => {
  /**
   * Sur un ecran de telephone, un retour a la ligne volait une deuxieme rangee
   * de hauteur juste au-dessus du clavier. La barre tient donc sur une ligne et
   * se fait defiler au doigt quand elle deborde.
   */
  function barre() {
    renderWithProviders(
      <TerminalKeybar
        onSend={vi.fn()}
        onPaste={vi.fn()}
        getSelection={() => ''}
        onSearch={vi.fn()}
        onToggleKeyboard={vi.fn()}
      />,
    )
    return screen.getByRole('toolbar')
  }

  it('ne renvoie pas les boutons a la ligne', () => {
    expect(barre().className).toContain('flex-nowrap')
  })

  it('laisse defiler horizontalement', () => {
    expect(barre().className).toContain('overflow-x-auto')
  })

  it('masque la barre de defilement', () => {
    // Elle mangerait une partie de la hauteur utile ; le geste suffit.
    expect(barre().className).toContain('scrollbar-none')
  })

  it('retient le geste en bout de course', () => {
    // Sans cela, continuer le geste declenche la navigation arriere de Safari.
    expect(barre().className).toContain('overscroll-x-contain')
  })

  it('empeche la compression des boutons', () => {
    // Sans `shrink-0`, flex les ecrase au lieu de laisser la barre defiler.
    barre()

    const boutons = screen.getAllByRole('button')
    expect(boutons.length).toBeGreaterThan(5)
    for (const bouton of boutons) {
      expect(bouton.className).toContain('shrink-0')
    }
  })
})

describe('TerminalKeybar — Entree et Echap', () => {
  function rendre(onSend = vi.fn()) {
    renderWithProviders(
      <TerminalKeybar onSend={onSend} onPaste={vi.fn()} getSelection={() => ''} />,
    )
    return onSend
  }

  it('envoie un retour chariot, pas un saut de ligne', async () => {
    // `\r` est ce qu'un terminal attend et ce que xterm emet sur la touche du
    // clavier physique ; `\n` laisserait la ligne non validee.
    const user = userEvent.setup()
    const onSend = rendre()

    await user.click(screen.getByRole('button', { name: /^entrée$|^enter$/i }))

    expect(onSend).toHaveBeenCalledWith('\r')
  })

  it('envoie bien Echap sur le bouton Echap', async () => {
    const user = userEvent.setup()
    const onSend = rendre()

    await user.click(screen.getByRole('button', { name: /^échap$|^esc$/i }))

    expect(onSend).toHaveBeenCalledWith('\x1b')
  })

  it('place Entree juste apres les fleches', async () => {
    // C'est la qu'on la cherche quand on vient de naviguer dans un menu.
    rendre()

    const noms = screen.getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? '')
    // La derniere fleche, quel que soit l'ordre des quatre.
    const derniereFleche = noms.map((n) => /flèche|arrow/i.test(n)).lastIndexOf(true)
    const entree = noms.findIndex((n) => /^entrée$|^enter$/i.test(n))

    expect(derniereFleche).toBeGreaterThan(0)
    expect(entree).toBe(derniereFleche + 1)
  })

  it('distingue Echap d’Entree a l’oeil', () => {
    // Les deux portaient la meme icone de retour chariot. Entree la garde ;
    // Echap s'ecrit, faute d'icone qui dise « echap ».
    rendre()

    const echap = screen.getByRole('button', { name: /^échap$|^esc$/i })
    const entree = screen.getByRole('button', { name: /^entrée$|^enter$/i })

    expect(echap.textContent?.trim().toLowerCase()).toBe('esc')
    expect(entree.querySelector('svg')).not.toBeNull()
    expect(entree.textContent?.trim()).toBe('')
  })
})
