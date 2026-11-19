import { useEffect, useRef, type KeyboardEvent } from 'react'

const focusable = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary'

export function useDialogFocus<T extends HTMLElement>(onClose?: () => void, open = true, initialFocus = '.modal-close') {
  const ref = useRef<T>(null)
  const initial = useRef(initialFocus)

  useEffect(() => {
    if (!open || !ref.current) return
    const previous = document.activeElement
    ref.current.querySelector<HTMLElement>(initial.current)?.focus({ preventScroll: true })
    return () => {
      if (previous instanceof HTMLElement) previous.focus({ preventScroll: true })
    }
  }, [open])

  const onKeyDown = (event: KeyboardEvent<T>) => {
    if (event.key === 'Escape' && onClose) {
      event.stopPropagation()
      onClose()
    }
    if (event.key !== 'Tab') return
    const nodes = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(focusable))
      .filter((node) => node.tabIndex >= 0 && node.getClientRects().length > 0)
    const first = nodes[0]
    const last = nodes[nodes.length - 1]
    if (event.shiftKey ? document.activeElement === first : document.activeElement === last) {
      event.preventDefault()
      const target = event.shiftKey ? last : first
      target?.focus()
    }
  }

  return { ref, onKeyDown }
}
