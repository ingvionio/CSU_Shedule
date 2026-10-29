import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { BellRing, Plus, RefreshCw, Send, Trash2, X } from 'lucide-react'

import { ApiError } from '../../api/client'
import { useAdminMessage, useAdminMessages, useDirections, useMessageMutations, useStudents } from '../../api/queries'
import type { AdminMessage, Group, Importance, MessageTarget, MessageTargetType, Student } from '../../types'
import { IMPORTANCE_HINTS, IMPORTANCE_TITLES, TARGET_TITLES, messageDate } from '../messages/labels'

const COURSES = [1, 2, 3, 4]
const IMPORTANCES: Importance[] = ['low', 'normal', 'high']
const TARGET_TYPES: MessageTargetType[] = ['all', 'course', 'direction', 'group', 'students']

type AdminMessagesProps = {
  token: string
  groups: Group[]
  /** Токен истёк или недействителен — нужно войти заново. */
  onUnauthorized: () => void
}

const isUnauthorized = (error: unknown) => error instanceof ApiError && error.status === 401

export function AdminMessages({ token, groups, onUnauthorized }: AdminMessagesProps) {
  const [composing, setComposing] = useState(false)
  const [openId, setOpenId] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const list = useAdminMessages(token)

  useEffect(() => {
    if (isUnauthorized(list.error)) onUnauthorized()
  }, [list.error, onUnauthorized])

  return (
    <section className="admin-schedule">
      <div className="admin-schedule-heading">
        <span className="eyebrow">АДМИНИСТРИРОВАНИЕ</span>
        <h1>Сообщения студентам</h1>
        <p className="muted">
          Получат студенты, которые заполнили профиль в приложении. Кто поставит приложение позже,
          увидит сообщения своей группе, курсу и потоку за последние две недели.
        </p>
      </div>

      {composing
        ? <MessageComposer
          token={token}
          groups={groups}
          onCancel={() => setComposing(false)}
          onSent={(message) => {
            setComposing(false)
            setNotice(message.recipients_total
              ? `Сообщение отправлено: получателей ${message.recipients_total}.`
              : 'Сообщение сохранено, но из адресатов пока никто не заполнил профиль. Его увидят, когда зарегистрируются.')
          }}
          onUnauthorized={onUnauthorized}
        />
        : <button className="button button-primary full" onClick={() => { setComposing(true); setNotice('') }}>
          <Plus size={16} />Новое сообщение
        </button>}
      {notice && <p className="success-note">{notice}</p>}

      {list.isError && !isUnauthorized(list.error) && (
        <div className="state-note error-note">
          <span>{(list.error as Error).message}</span>
          <button className="button button-secondary" onClick={() => list.refetch()}><RefreshCw size={16} />Повторить</button>
        </div>
      )}
      {list.isLoading && <div className="state-note">Загружаем сообщения…</div>}
      {list.data && !list.data.length && <div className="empty-day">Сообщений пока нет.</div>}

      <div className="feedback-list">
        {list.data?.map((item) => (
          <button key={item.id} className="feedback-card feedback-card-button" onClick={() => setOpenId(item.id)}>
            <div className="feedback-card-head">
              <span>{item.target_title} · {messageDate(item.sent_at)}</span>
              <span className={`badge importance-${item.importance}`}>{IMPORTANCE_TITLES[item.importance]}</span>
            </div>
            <strong className="message-title">{item.title}</strong>
            <ReadProgress item={item} />
          </button>
        ))}
      </div>

      {openId !== null && (
        <MessageDetailDialog id={openId} token={token} onClose={() => setOpenId(null)} onUnauthorized={onUnauthorized} />
      )}
    </section>
  )
}

function ReadProgress({ item }: { item: AdminMessage }) {
  const done = item.importance === 'high' ? item.acknowledged_count : item.read_count
  const percent = item.recipients_total ? Math.round((done / item.recipients_total) * 100) : 0
  return (
    <div className="read-progress">
      <div className="read-progress-bar"><i style={{ width: `${percent}%` }} /></div>
      <small>
        Прочитали {item.read_count} из {item.recipients_total}
        {item.importance === 'high' ? ` · подтвердили ${item.acknowledged_count}` : ''}
      </small>
    </div>
  )
}

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value]
}

function MessageComposer({
  token,
  groups,
  onCancel,
  onSent,
  onUnauthorized,
}: {
  token: string
  groups: Group[]
  onCancel: () => void
  onSent: (message: AdminMessage) => void
  onUnauthorized: () => void
}) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [importance, setImportance] = useState<Importance>('normal')
  const [type, setType] = useState<MessageTargetType>('group')
  const [courses, setCourses] = useState<number[]>([])
  const [directions, setDirections] = useState<string[]>([])
  const [groupIds, setGroupIds] = useState<number[]>([])
  const [students, setStudents] = useState<Student[]>([])
  const [error, setError] = useState('')
  const { send } = useMessageMutations(token)
  const directionList = useDirections()

  const target: MessageTarget = { type }
  if (type === 'course') target.courses = courses
  if (type === 'direction') Object.assign(target, { directions, courses })
  if (type === 'group') target.group_ids = groupIds
  if (type === 'students') target.user_ids = students.map((student) => student.id)

  /** Почему отправить нельзя; пустая строка — можно. */
  const problem = !title.trim() || !body.trim()
    ? 'Заполните заголовок и текст.'
    : (type === 'course' && !courses.length) || (type === 'direction' && !directions.length)
      || (type === 'group' && !groupIds.length) || (type === 'students' && !students.length)
      ? 'Выберите, кому отправить.'
      : ''

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(problem)
    if (problem) return
    try {
      onSent(await send.mutateAsync({ title: title.trim(), body: body.trim(), importance, target }))
    } catch (reason) {
      if (isUnauthorized(reason)) onUnauthorized()
      else setError((reason as Error).message)
    }
  }

  return (
    <form className="screen-card selection-screen message-composer" onSubmit={submit}>
      <div className="eyebrow">НОВОЕ СООБЩЕНИЕ</div>

      <label className="admin-field">
        <span>Заголовок</span>
        <input className="text-field" maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label className="admin-field">
        <span>Текст</span>
        <textarea className="text-field text-area" rows={5} maxLength={8000} value={body} onChange={(event) => setBody(event.target.value)} />
      </label>

      <span className="field-label">Важность</span>
      <div className="choice-row three">
        {IMPORTANCES.map((value) => (
          <button type="button" key={value} className={`choice ${importance === value ? 'selected' : ''}`} onClick={() => setImportance(value)}>
            {IMPORTANCE_TITLES[value]}
          </button>
        ))}
      </div>
      <p className="feedback-hint">{IMPORTANCE_HINTS[importance]}</p>

      <span className="field-label">Кому</span>
      <div className="choice-row five">
        {TARGET_TYPES.map((value) => (
          <button type="button" key={value} className={`choice ${type === value ? 'selected' : ''}`} onClick={() => setType(value)}>
            {TARGET_TITLES[value]}
          </button>
        ))}
      </div>

      {type === 'all' && <p className="feedback-hint">Все студенты с профилем в приложении.</p>}

      {type === 'direction' && (
        <>
          <span className="field-label">Направление</span>
          <div className="feedback-filters">
            {(directionList.data ?? []).map((item) => (
              <button type="button" key={item.code} className={`choice ${directions.includes(item.code) ? 'selected' : ''}`}
                onClick={() => setDirections((value) => toggle(value, item.code))}>{item.code}</button>
            ))}
          </div>
        </>
      )}

      {(type === 'course' || type === 'direction') && (
        <>
          <span className="field-label">
            Курс {type === 'direction' && <span className="optional">— не выбран, значит все курсы</span>}
          </span>
          <div className="choice-row">
            {COURSES.map((course) => (
              <button type="button" key={course} className={`choice ${courses.includes(course) ? 'selected' : ''}`}
                onClick={() => setCourses((value) => toggle(value, course))}>{course}</button>
            ))}
          </div>
        </>
      )}

      {type === 'group' && <GroupPicker groups={groups} selected={groupIds} onChange={setGroupIds} />}

      {type === 'students' && <StudentPicker token={token} selected={students} onChange={setStudents} />}

      {error && problem && <p className="form-error" role="alert">{problem}</p>}
      {error && !problem && <p className="form-error" role="alert">{error}</p>}
      <div className="admin-time-row">
        <button type="button" className="button button-secondary" onClick={onCancel}>Отмена</button>
        <button className="button button-primary" disabled={send.isPending}>
          <Send size={16} />{send.isPending ? 'Отправляем…' : 'Отправить'}
        </button>
      </div>
    </form>
  )
}

function GroupPicker({ groups, selected, onChange }: { groups: Group[]; selected: number[]; onChange: (ids: number[]) => void }) {
  const byCourse = useMemo(() => {
    const result = new Map<number, Group[]>()
    for (const group of groups) result.set(group.course, [...(result.get(group.course) ?? []), group])
    return [...result.entries()].sort(([a], [b]) => a - b)
  }, [groups])

  return (
    <>
      {byCourse.map(([course, items]) => (
        <fieldset key={course} className="stream-groups">
          <legend>{course} курс</legend>
          {items.map((group) => (
            <label key={group.id}>
              <input type="checkbox" checked={selected.includes(group.id)} onChange={() => onChange(toggle(selected, group.id))} />
              <span>{group.name}</span>
            </label>
          ))}
        </fieldset>
      ))}
    </>
  )
}

function StudentPicker({ token, selected, onChange }: { token: string; selected: Student[]; onChange: (students: Student[]) => void }) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [query])
  const found = useStudents(token, { q: debounced || undefined }, debounced.length >= 2)
  const selectedIds = selected.map((student) => student.id)

  return (
    <>
      <label className="admin-field">
        <span>Поиск по ФИО</span>
        <input className="text-field" placeholder="Хотя бы две буквы" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      {selected.length > 0 && (
        <div className="feedback-filters">
          {selected.map((student) => (
            <button type="button" key={student.id} className="choice selected"
              onClick={() => onChange(selected.filter((item) => item.id !== student.id))}>
              {student.full_name} <X size={12} />
            </button>
          ))}
        </div>
      )}
      {found.data && (
        <fieldset className="stream-groups single">
          <legend>Найдено: {found.data.length}</legend>
          {found.data.map((student) => (
            <label key={student.id}>
              <input
                type="checkbox"
                checked={selectedIds.includes(student.id)}
                onChange={() => onChange(selectedIds.includes(student.id)
                  ? selected.filter((item) => item.id !== student.id)
                  : [...selected, student])}
              />
              <span>{student.full_name} · {student.group_name ?? 'без группы'}</span>
            </label>
          ))}
        </fieldset>
      )}
    </>
  )
}

function MessageDetailDialog({
  id,
  token,
  onClose,
  onUnauthorized,
}: {
  id: number
  token: string
  onClose: () => void
  onUnauthorized: () => void
}) {
  const detail = useAdminMessage(token, id)
  const { remind, remove } = useMessageMutations(token)
  const [onlyPending, setOnlyPending] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (isUnauthorized(detail.error)) onUnauthorized()
  }, [detail.error, onUnauthorized])

  const message = detail.data
  const needsAck = message?.importance === 'high'
  const isPending = (item: { read_at: string | null; acknowledged_at: string | null }) =>
    needsAck ? !item.acknowledged_at : !item.read_at
  const recipients = (message?.recipients ?? []).filter((item) => !onlyPending || isPending(item))
  const pendingCount = (message?.recipients ?? []).filter(isPending).length

  const run = async (action: () => Promise<unknown>) => {
    setError('')
    setNotice('')
    try {
      await action()
    } catch (reason) {
      if (isUnauthorized(reason)) onUnauthorized()
      else setError((reason as Error).message)
    }
  }

  const sendReminder = () => run(async () => {
    const result = await remind.mutateAsync(id)
    await detail.refetch()
    setNotice(result.reminded ? `Напоминание отправлено: ${result.reminded}.` : 'Напоминать некому — все прочитали.')
  })

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="confirm-modal feedback-dialog" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" aria-label="Закрыть" onClick={onClose}><X size={17} /></button>
        {detail.isLoading && <div className="state-note">Загружаем…</div>}
        {detail.isError && !isUnauthorized(detail.error) && <p className="form-error">{(detail.error as Error).message}</p>}

        {message && <>
          <span className="eyebrow">{IMPORTANCE_TITLES[message.importance].toUpperCase()} · {message.target_title}</span>
          <h2>{message.title}</h2>
          <p className="feedback-text feedback-original">{message.body}</p>
          <dl className="feedback-meta">
            <dt>Отправлено</dt><dd>{messageDate(message.sent_at)}{message.created_by ? ` · ${message.created_by}` : ''}</dd>
            {message.last_reminded_at && <><dt>Напоминание</dt><dd>{messageDate(message.last_reminded_at)}</dd></>}
          </dl>
          <ReadProgress item={message} />

          {message.importance !== 'low' && (
            <button className="button button-secondary full" disabled={remind.isPending || pendingCount === 0} onClick={sendReminder}>
              <BellRing size={16} />
              {pendingCount ? `Напомнить ${needsAck ? 'неподтвердившим' : 'непрочитавшим'} (${pendingCount})` : 'Все прочитали'}
            </button>
          )}
          {notice && <p className="success-note">{notice}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}

          <div className="segmented">
            <button className={!onlyPending ? 'active' : ''} onClick={() => setOnlyPending(false)}>Все · {message.recipients.length}</button>
            <button className={onlyPending ? 'active' : ''} onClick={() => setOnlyPending(true)}>
              {needsAck ? 'Не подтвердили' : 'Не прочитали'} · {pendingCount}
            </button>
          </div>
          {recipients.length
            ? <ul className="recipient-status-list">
              {recipients.map((item) => (
                <li key={item.user_id}>
                  <div>
                    <strong>{item.full_name}</strong>
                    <small>{item.group_name ?? 'без группы'}</small>
                  </div>
                  <small className={isPending(item) ? 'pending' : 'done'}>
                    {item.acknowledged_at
                      ? `ознакомлен ${messageDate(item.acknowledged_at)}`
                      : item.read_at ? `прочитал ${messageDate(item.read_at)}` : 'не открывал'}
                  </small>
                </li>
              ))}
            </ul>
            : <div className="empty-day">{onlyPending ? 'Все прочитали.' : 'Получателей пока нет.'}</div>}

          {confirmDelete
            ? <div className="admin-time-row">
              <button className="button button-secondary" onClick={() => setConfirmDelete(false)}>Не удалять</button>
              <button className="button button-primary" disabled={remove.isPending} onClick={() => run(async () => {
                await remove.mutateAsync(id)
                onClose()
              })}>Удалить у всех</button>
            </div>
            : <button className="quiet-link" onClick={() => setConfirmDelete(true)}><Trash2 size={14} />Удалить сообщение</button>}
        </>}
      </div>
    </div>
  )
}
