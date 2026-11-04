import { useEffect, useRef, useState } from 'react'
import { LockKeyhole, X } from 'lucide-react'

import { usePersonalNoteMutations } from '../../api/queries'
import type { PersonalNote } from '../../api/types'
import type { Day, Lesson } from '../../types'
import { dayLabel } from '../../ScheduleComponents'

export function PersonalNoteDialog({ groupId, day, lesson, note, onClose }: {
  groupId: number; day: Day; lesson: Lesson; note?: PersonalNote; onClose: () => void
}) {
  const [body, setBody] = useState(note?.body ?? '')
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [closing, setClosing] = useState(false)
  const mutations = usePersonalNoteMutations()
  const busy = mutations.save.isPending || mutations.remove.isPending
  const textarea = useRef<HTMLTextAreaElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const close = () => setClosing(true)

  useEffect(() => {
    if (!closing) return
    const timer = window.setTimeout(onClose, 180)
    return () => window.clearTimeout(timer)
  }, [closing, onClose])

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    if (note) closeButton.current?.focus()
    else textarea.current?.focus()
    return () => {
      document.body.style.overflow = previousOverflow
      previous?.focus()
    }
  }, [])

  const save = async () => {
    setError('')
    try {
      await mutations.save.mutateAsync({ group_id: groupId, lesson_date: day.date, lesson_ref: lesson.id,
        body: body.trim(), version: note?.version ?? 0 })
      close()
    } catch (reason) { setError((reason as Error).message) }
  }

  const remove = async () => {
    if (!note) return
    setError('')
    try {
      await mutations.remove.mutateAsync({ id: note.id, version: note.version })
      close()
    } catch (reason) { setError((reason as Error).message) }
  }

  return <div className={`modal-backdrop personal-note-backdrop${closing ? ' closing' : ''}`} onMouseDown={(event) => { if (!busy && event.target === event.currentTarget) close() }}>
    <section className="confirm-modal personal-note-dialog" role="dialog" aria-modal="true" aria-labelledby="personal-note-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !busy) close()
        if (event.key === 'Tab') {
          const nodes = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), textarea'))
          const first = nodes[0], last = nodes[nodes.length - 1]
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
          if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
        }
      }}>
      <button ref={closeButton} className="modal-close" aria-label="Закрыть" disabled={busy || closing} onClick={close}><X size={18} /></button>
      <h2 id="personal-note-title">Моя заметка</h2>
      <p className="private-note-caption"><LockKeyhole size={16} />Видна только вам</p>
      <div className="admin-selected-lesson"><strong>{lesson.subject}</strong><span>{dayLabel(day.date)} · {lesson.start_time}–{lesson.end_time}</span><span>{[lesson.type.name, lesson.teacher, lesson.room ? `Ауд. ${lesson.room}` : null].filter(Boolean).join(' · ')}</span></div>
      <label className="admin-field"><span>Текст заметки</span><textarea ref={textarea} className="text-field" rows={6} maxLength={5000} value={body} onChange={(event) => setBody(event.target.value)} placeholder="Что повторить, о чём спросить, что взять с собой…" /></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button button-primary full" disabled={busy || closing || !body.trim()} onClick={save}>{busy ? 'Сохраняем…' : 'Сохранить заметку'}</button>
      {note && (confirmDelete
        ? <div className="note-delete-confirm"><span>Удалить заметку?</span><button className="button button-secondary" disabled={busy} onClick={remove}>Удалить</button><button className="quiet-link" disabled={busy} onClick={() => setConfirmDelete(false)}>Отмена</button></div>
        : <button className="quiet-link centered" disabled={busy} onClick={() => setConfirmDelete(true)}>Удалить заметку</button>)}
    </section>
  </div>
}
