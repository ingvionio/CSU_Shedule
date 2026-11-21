import type { ReactNode } from 'react'
import type { ExamOriginal, ExamType, ExamValues } from '../../api/types'

export const examTypeLabels: Record<ExamType, string> = {
  consultation: 'Консультация', exam: 'Экзамен', credit: 'Зачёт', graded_credit: 'Дифф. зачёт', other: 'Другое',
}

export function examDateLabel(value: string) {
  const date = new Date(value + 'T12:00:00')
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }) + ', ' + date.toLocaleDateString('ru-RU', { weekday: 'short' })
}

export function AdminExamCard({ event, original, cancelled, children }: {
  event: Omit<ExamValues, 'kind' | 'event_type'> & {
    event_type?: ExamType | null; type?: { code: ExamType; name: string } | null
  }; original: ExamOriginal; cancelled: boolean; children?: ReactNode
}) {
  const type = event.type ?? (event.event_type ? { code: event.event_type, name: examTypeLabels[event.event_type] } : null)
  return <article className={'exam-card ' + (type ? 'exam-type-' + type.code + ' ' : '') + (cancelled ? 'exam-cancelled' : '')}>
    <div className="exam-main">
      {type && <span className="badge exam-type-badge">{type.name}</span>}
      <p className="exam-time">
        {original && 'start_time' in original && <del>{original.start_time ?? 'Время не указано'}</del>}{' '}
        {event.start_time ?? 'Время не указано'}
        {cancelled && <strong className="badge badge-cancelled">Отменено</strong>}
      </p>
      <h3>{event.subject}</h3>
      {original?.date && <p className="change-note"><del>{examDateLabel(original.date)}</del> → {examDateLabel(event.date)}</p>}
      {event.teacher && <p>{event.teacher}</p>}
      {(event.room || (original && 'room' in original)) && <p>
        {original && 'room' in original && <del>{original.room ?? 'Аудитория не указана'}</del>}{' '}{event.room ?? 'Аудитория не указана'}
      </p>}
      {event.note && <p className="exam-note">{event.note}</p>}
    </div>
    {children}
  </article>
}
