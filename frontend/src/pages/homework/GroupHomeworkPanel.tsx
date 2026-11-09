import { ContextHelp } from '../../ContextHelp'
import { useMemo, useState } from 'react'
import { Check, Plus, RotateCcw } from 'lucide-react'

import { useStudentSession } from '../../api/student'
import { ApiError } from '../../api/client'
import { useHomework, useHomeworkMutations } from '../../api/queries'
import type { Day, GroupHomework, HomeworkSource } from '../../types'
import { dayLabel } from '../../ScheduleComponents'

const SOURCE_LABELS: Record<HomeworkSource, string> = {
  from_class: 'Сказано на паре',
  moodle: 'Moodle',
  chat: 'Из чата группы',
  unknown: 'Источник не указан',
}

type Props = { groupId: number | null; weekStart: string; weekEnd: string; days: Day[]; selectedDay: number }

export function GroupHomeworkPanel({ groupId, weekStart, weekEnd, days, selectedDay }: Props) {
  const session = useStudentSession()
  const sameGroup = groupId === session?.profile.group_id
  const homework = useHomework(groupId !== null && sameGroup, weekStart, weekEnd)
  const mutations = useHomeworkMutations()
  const [expanded, setExpanded] = useState(false)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [lessonDate, setLessonDate] = useState(days[selectedDay]?.date ?? weekStart)
  const [lessonId, setLessonId] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [source, setSource] = useState<HomeworkSource>('from_class')
  const [error, setError] = useState('')

  const lessons = useMemo(() => days.flatMap((day) => day.lessons
    .filter((lesson) => lesson.id.startsWith('l-'))
    .map((lesson) => ({ day, lesson }))), [days])

  const submit = async () => {
    if (!title.trim()) return
    setError('')
    try {
      await mutations.create.mutateAsync({
        title: title.trim(), body: body.trim(), lesson_date: lessonDate || null,
        lesson_id: lessonId ? Number(lessonId) : null, due_date: dueDate || null, source,
      })
      setTitle(''); setBody(''); setLessonId(''); setDueDate(''); setExpanded(false)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Не удалось сохранить домашку')
    }
  }

  const toggle = async (item: GroupHomework) => {
    try {
      await mutations.complete.mutateAsync({ id: item.id, completed: !item.completed_by_me })
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Не удалось изменить статус')
    }
  }

  if (groupId === null || !sameGroup) return null
  if (homework.isError && !homework.data) return <div className="state-note error-note"><span>{homework.error.message}</span><button className="button button-secondary" onClick={() => homework.refetch()}>Повторить</button></div>
  if (!homework.data) return <div className="state-note">Загружаем домашку…</div>
  const items = homework.data.items

  return <section className="screen-card homework-panel">
    <div className="homework-heading">
      <div>
        <span className="eyebrow">ГРУППОВАЯ ДОМАШКА</span>
        <h2>Задания на эту неделю</h2>
        <p className="muted">Общие записи группы. Отметка выполнения видна только вам.</p>
        <ContextHelp ids={['homework', 'notes']} label="Домашка и личные заметки" />
      </div>
      {homework.data.can_edit && <button className="button button-secondary" onClick={() => setExpanded((value) => !value)}>
        <Plus size={16} />{expanded ? 'Закрыть' : 'Добавить'}
      </button>}
    </div>

    <p className="homework-profile muted">{session?.profile.full_name} · профиль №{session?.profile.id}{homework.data.can_edit ? ' · редактор группы' : ' · просмотр заданий'}</p>
    {expanded && <div className="homework-form">
      <label className="admin-field"><span>Название задания</span><input className="text-field" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Например: лабораторная №2" /></label>
      <label className="admin-field"><span>Описание</span><textarea className="text-field" value={body} onChange={(event) => setBody(event.target.value)} placeholder="Что нужно сделать" rows={3} /></label>
      <div className="admin-time-row">
        <label className="admin-field"><span>К какой паре</span><select className="select-field" value={lessonId} onChange={(event) => {
          const value = event.target.value; setLessonId(value)
          const match = lessons.find(({ lesson }) => lesson.id.slice(2) === value)
          if (match) {
            setLessonDate(match.day.date)
            setDueDate(match.day.date)
          }
        }}><option value="">Без конкретной пары</option>{lessons.map(({ day, lesson }) => <option key={lesson.id} value={lesson.id.slice(2)}>{dayLabel(day.date)} · {lesson.start_time} · {lesson.subject}</option>)}</select></label>
        <label className="admin-field"><span>Срок сдачи</span><input className="text-field" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
      </div>
      <label className="admin-field"><span>Источник</span><select className="select-field" value={source} onChange={(event) => setSource(event.target.value as HomeworkSource)}>{Object.entries(SOURCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button button-primary" disabled={!title.trim() || mutations.create.isPending} onClick={submit}>{mutations.create.isPending ? 'Публикуем…' : 'Опубликовать для группы'}</button>
    </div>}

    {error && !expanded && <p className="form-error" role="alert">{error}</p>}
    {items.length === 0 ? <div className="empty-day">На этой неделе заданий нет.</div> : <div className="homework-list">
      {items.map((item) => <article className={`homework-item ${item.completed_by_me ? 'completed' : ''}`} key={item.id}>
        <button className="homework-check" aria-label={item.completed_by_me ? 'Вернуть в работу' : 'Отметить выполненным'} onClick={() => toggle(item)}>{item.completed_by_me ? <Check size={16} /> : <span />}</button>
        <div className="homework-main"><div className="homework-title-row"><strong>{item.title}</strong>{item.due_date && <span className="homework-due">до {new Date(`${item.due_date}T00:00:00`).toLocaleDateString('ru-RU')}</span>}</div>
          {item.subject && <span className="muted">{item.subject}{item.lesson_date ? ` · ${dayLabel(item.lesson_date)}` : ''}</span>}
          {item.body && <p>{item.body}</p>}
          <small className="muted">{SOURCE_LABELS[item.source]} · добавил(а) {item.created_by_name}</small>
        </div>
      </article>)}
    </div>}
    {homework.data.can_edit && <div className="homework-editor-note"><RotateCcw size={14} /> Вы редактор домашки этой группы. Все изменения сохраняются в истории.</div>}
  </section>
}
