import type { ReactNode } from 'react'
import type { ExamOriginal, ExamValues } from '../../api/types'

export function examDateLabel(value: string) {
  const date = new Date(value + 'T12:00:00')
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }) + ', ' + date.toLocaleDateString('ru-RU', { weekday: 'short' })
}

export function ExamCard({ event, original, cancelled, children }: {
  event: Omit<ExamValues, 'kind'>; original: ExamOriginal; cancelled: boolean; children?: ReactNode
}) {
  return <article className={'exam-card ' + (cancelled ? 'exam-cancelled' : '')}>
    <div className="exam-main">
      <p className="exam-time">
        {original.original_start_time && <del>{original.original_start_time}</del>}{' '}
        {event.start_time ?? 'Время не указано'}
        {cancelled && <strong className="badge badge-cancelled">Отменено</strong>}
      </p>
      <h3>{event.subject}</h3>
      {original.original_date && <p className="change-note"><del>{examDateLabel(original.original_date)}</del> → {examDateLabel(event.date)}</p>}
      {event.teacher && <p>{event.teacher}</p>}
      {(event.room || original.original_room) && <p><del>{original.original_room}</del>{' '}{event.room ?? 'Аудитория не указана'}</p>}
      {event.note && <p className="exam-note">{event.note}</p>}
    </div>
    {children}
  </article>
}
