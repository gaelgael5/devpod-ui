import { useEffect, useRef, useState } from 'react'
import type { ClipboardEvent, FormEvent, KeyboardEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface PinInputProps {
  onComplete: (pin: string) => void
  disabled?: boolean
  /** Affiche un bouton Valider et déplace le focus dessus au dernier chiffre. */
  showSubmit?: boolean
  className?: string
}

const PIN_LENGTH = 6
const MASK_DELAY_MS = 1000

export function PinInput({ onComplete, disabled, showSubmit = false, className }: PinInputProps) {
  const [digits, setDigits] = useState<string[]>(Array(PIN_LENGTH).fill(''))
  const [visible, setVisible] = useState<Set<number>>(new Set())
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])
  const submitRef = useRef<HTMLButtonElement>(null)
  const maskTimers = useRef<(ReturnType<typeof setTimeout> | undefined)[]>(
    Array(PIN_LENGTH).fill(undefined),
  )

  useEffect(() => {
    inputRefs.current[0]?.focus()
  }, [])

  useEffect(() => {
    const timers = maskTimers.current
    return () => timers.forEach(t => clearTimeout(t))
  }, [])

  const update = (i: number, rawValue: string) => {
    const digit = rawValue.replace(/\D/g, '').slice(-1)

    clearTimeout(maskTimers.current[i])
    maskTimers.current[i] = undefined

    const d = [...digits]
    d[i] = digit
    setDigits(d)

    if (digit) {
      setVisible(prev => { const next = new Set(prev); next.add(i); return next })
      maskTimers.current[i] = setTimeout(() => {
        setVisible(v => { const s = new Set(v); s.delete(i); return s })
      }, MASK_DELAY_MS)
    } else {
      setVisible(prev => { const next = new Set(prev); next.delete(i); return next })
    }

    if (digit) {
      const allFilled = d.every(Boolean)
      if (allFilled) {
        if (showSubmit) submitRef.current?.focus()
        else onComplete(d.join(''))
      } else if (i < PIN_LENGTH - 1) {
        inputRefs.current[i + 1]?.focus()
      }
    }
  }

  const handleKey = (i: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !digits[i] && i > 0) {
      inputRefs.current[i - 1]?.focus()
    }
  }

  const handlePaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, PIN_LENGTH)
    if (!pasted) return

    const d = [...digits]
    const newVisible = new Set<number>()

    for (let j = 0; j < pasted.length; j++) {
      d[j] = pasted[j]
      newVisible.add(j)
      clearTimeout(maskTimers.current[j])
      maskTimers.current[j] = setTimeout(() => {
        setVisible(v => { const s = new Set(v); s.delete(j); return s })
      }, MASK_DELAY_MS)
    }

    setDigits(d)
    setVisible(newVisible)

    const allFilled = pasted.length === PIN_LENGTH
    if (allFilled) {
      if (showSubmit) submitRef.current?.focus()
      else onComplete(pasted)
    } else {
      inputRefs.current[Math.min(pasted.length, PIN_LENGTH - 1)]?.focus()
    }
  }

  const displayValue = (i: number): string => {
    if (!digits[i]) return ''
    return visible.has(i) ? digits[i] : '*'
  }

  const allFilled = digits.every(Boolean)

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (allFilled && !disabled) onComplete(digits.join(''))
  }

  return (
    <form onSubmit={handleSubmit} className={cn('flex flex-col gap-4', className)}>
      <div className="flex justify-center gap-2">
        {digits.map((_, i) => (
          <Input
            key={i}
            ref={(el) => { inputRefs.current[i] = el }}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            maxLength={1}
            value={displayValue(i)}
            onChange={(e) => update(i, e.target.value)}
            onKeyDown={(e) => handleKey(i, e)}
            onPaste={handlePaste}
            disabled={disabled}
            className="h-12 w-12 text-center font-mono text-xl"
          />
        ))}
      </div>
      {showSubmit && (
        <Button
          ref={submitRef}
          type="submit"
          disabled={!allFilled || disabled}
          className="w-full"
        >
          {disabled ? 'Vérification…' : 'Valider'}
        </Button>
      )}
    </form>
  )
}
