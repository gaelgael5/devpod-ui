import { useRef, useState } from 'react'
import type { ClipboardEvent, KeyboardEvent } from 'react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface PinInputProps {
  onComplete: (pin: string) => void
  disabled?: boolean
  className?: string
}

export function PinInput({ onComplete, disabled, className }: PinInputProps) {
  const [digits, setDigits] = useState<string[]>(Array(6).fill(''))
  const refs = useRef<(HTMLInputElement | null)[]>([])

  const update = (i: number, value: string) => {
    const d = [...digits]
    d[i] = value.replace(/\D/g, '').slice(-1)
    setDigits(d)
    if (d[i] && i < 5) refs.current[i + 1]?.focus()
    const pin = d.join('')
    if (pin.length === 6) onComplete(pin)
  }

  const handleKey = (i: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !digits[i] && i > 0) refs.current[i - 1]?.focus()
  }

  const handlePaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    const d = [...digits]
    for (let j = 0; j < pasted.length; j++) d[j] = pasted[j]
    setDigits(d)
    refs.current[Math.min(pasted.length, 5)]?.focus()
    if (pasted.length === 6) onComplete(pasted)
  }

  return (
    <div className={cn('flex gap-2', className)}>
      {digits.map((digit, i) => (
        <Input
          key={i}
          ref={(el) => {
            refs.current[i] = el
          }}
          type="text"
          inputMode="numeric"
          maxLength={1}
          value={digit}
          onChange={(e) => update(i, e.target.value)}
          onKeyDown={(e) => handleKey(i, e)}
          onPaste={handlePaste}
          disabled={disabled}
          className="h-12 w-12 text-center font-mono text-xl"
        />
      ))}
    </div>
  )
}
