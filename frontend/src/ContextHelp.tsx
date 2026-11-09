import { CircleHelp } from 'lucide-react'
import { helpItems } from './pages/helpContent'

/** Native disclosure works with touch, keyboard and screen readers, without hover. */
type HelpEntry = { id: string; question: string; answer: string }

export function ContextHelp({ ids, label = 'Как это работает', compact = false, items = helpItems }: {
  ids: string[]; label?: string; compact?: boolean; items?: readonly HelpEntry[]
}) {
  return <details className={`context-help${compact ? ' context-help-compact' : ''}`}><summary title={compact ? label : undefined}><CircleHelp size={compact ? 20 : 15} /><span className={compact ? 'sr-only' : undefined}>{label}</span></summary><div>{ids.map(id => {
    const item = items.find(entry => entry.id === id)
    return item && <p key={id}><strong>{item.question}</strong>{item.answer}</p>
  })}</div></details>
}
