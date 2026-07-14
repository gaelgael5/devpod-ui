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
    renderWithProviders(<TerminalKeybar onSend={onSend} getSelection={() => ''} />)

    await user.click(screen.getByRole('button', { name: /échap|esc/i }))
    expect(onSend).toHaveBeenCalledWith('\x1b')

    await user.click(screen.getByRole('button', { name: /interrompre|interrupt/i }))
    expect(onSend).toHaveBeenCalledWith('\x03')
  })

  it('colle le presse-papier dans le stdin', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    stubClipboard({ readText: vi.fn().mockResolvedValue('salut'), writeText: vi.fn() })
    renderWithProviders(<TerminalKeybar onSend={onSend} getSelection={() => ''} />)

    await user.click(screen.getByRole('button', { name: /coller|paste/i }))
    await waitFor(() => expect(onSend).toHaveBeenCalledWith('salut'))
  })

  it('copie la sélection du terminal vers le presse-papier', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubClipboard({ readText: vi.fn(), writeText })
    renderWithProviders(
      <TerminalKeybar onSend={vi.fn()} getSelection={() => 'ligne sélectionnée'} />
    )

    await user.click(screen.getByRole('button', { name: /copier|copy/i }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('ligne sélectionnée'))
    expect(toast.success).toHaveBeenCalled()
  })

  it('signale une sélection vide sans écrire dans le presse-papier', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn()
    stubClipboard({ readText: vi.fn(), writeText })
    renderWithProviders(<TerminalKeybar onSend={vi.fn()} getSelection={() => ''} />)

    await user.click(screen.getByRole('button', { name: /copier|copy/i }))
    expect(writeText).not.toHaveBeenCalled()
    expect(toast.info).toHaveBeenCalled()
  })
})
