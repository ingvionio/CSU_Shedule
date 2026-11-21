import { useState } from 'react'
import { useExams } from '../../api/queries'
import type { ExamKind, StudentExam } from '../../api/types'
import { ExamCard, examDateLabel } from './ExamCard'

const kindLabels = { session: 'Сессия', retake: 'Пересдачи' }

function relativeDate(days: number): string {
  if (days === 0) return 'сегодня'
  if (days === 1) return 'завтра'
  return 'через ' + days + ' дней'
}

function ExamDates({ events, groupName }: { events: StudentExam[]; groupName: string }) {
  const dates = new Map<string, StudentExam[]>()
  for (const event of events) dates.set(event.date, [...(dates.get(event.date) ?? []), event])
  return <>{[...dates].map(([date, items]) => <section className="exam-date" key={date}>
    <h2>{examDateLabel(date)} {!items[0].is_past && <small>{relativeDate(items[0].days_left)}</small>}</h2>
    {items.map(event => <ExamCard key={event.id} event={event} cancelled={event.status === 'cancelled'} original={{
      original_date: event.change?.date ?? null, original_start_time: event.change?.start_time ?? null,
      original_room: event.change?.room ?? null,
    }}>
      {event.status === 'changed' && <span className="badge badge-changed">Изменено</span>}
      {event.groups.some(group => group !== groupName) && <p className="muted">Вместе с {event.groups.filter(group => group !== groupName).join(', ')}</p>}
    </ExamCard>)}
  </section>)}</>
}

export function StudentExams({ groupId }: { groupId: number }) {
  const query = useExams(groupId)
  const [selectedKind, setKind] = useState<ExamKind>('session')
  const data = query.data
  const kind = data?.kinds.includes(selectedKind) ? selectedKind : data?.kinds[0]
  const events = data?.events.filter(event => event.kind.code === kind) ?? []
  const upcoming = events.filter(event => !event.is_past)
  const past = events.filter(event => event.is_past)
  return <section className="exam-screen">
    <h1>Сессия и пересдачи</h1>
    {data && data.kinds.length > 1 && <div className="segmented" aria-label="Вид событий">
      {data.kinds.map(code => <button key={code} className={kind === code ? 'active' : ''} onClick={() => setKind(code)}>{kindLabels[code]}</button>)}
    </div>}
    {query.isError && <div className="state-note error-note"><span>{query.error.message}</span><button className="button button-secondary" onClick={() => void query.refetch()}>Повторить</button></div>}
    {!data && query.isPending && <p className="state-note">Загружаем сессию…</p>}
    {data && events.length === 0 && <p className="empty-day">Расписание сессии пока не опубликовано</p>}
    {data && <ExamDates events={upcoming} groupName={data.group.name} />}
    {data && past.length > 0 && <details className="exam-past"><summary>Прошедшие ({past.length})</summary><ExamDates events={past} groupName={data.group.name} /></details>}
    {data && !navigator.onLine && <p className="state-note muted">Показано сохранённое расписание сессии</p>}
  </section>
}
