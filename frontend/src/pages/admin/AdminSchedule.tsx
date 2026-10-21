import { useEffect, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, X } from 'lucide-react'

import { ApiError } from '../../api/client'
import { useCatalog, useLessonTypes, useOverrideMutations } from '../../api/queries'
import { WeekGrid, changeDetails, dayLabel } from '../../ScheduleComponents'
import type { Day, Group, Lesson, OverrideInput, OverrideKind, TimeSlot, WeekSchedule } from '../../types'

type SelectedCell =
  | { kind: 'lesson'; day: Day; lesson: Lesson }
  | { kind: 'empty'; day: Day; slot: TimeSlot }

/** Время пары: номер из сетки звонков или своё время (пара вне сетки). */
type TimeChoice = number | 'custom'

type AdminScheduleProps = {
  groups: Group[]
  groupId: number | null
  schedule?: WeekSchedule
  days: Day[]
  slots: TimeSlot[]
  currentMinutes: number
  token: string
  onGroupChange: (id: number) => void
  onWeekMove: (delta: number) => void
  /** Токен истёк или недействителен — нужно войти заново. */
  onUnauthorized: () => void
}

const ACTION_TITLES: Record<OverrideKind, string> = {
  cancel: 'Отменить пару',
  move: 'Перенести пару',
  replace: 'Заменить данные пары',
  add: 'Добавить пару',
}

const SUBMIT_LABELS: Record<OverrideKind, string> = {
  cancel: 'Отменить пару',
  move: 'Перенести',
  replace: 'Сохранить замену',
  add: 'Добавить пару',
}

const DONE_LABELS: Record<OverrideKind, string> = {
  cancel: 'Пара отменена',
  move: 'Пара перенесена',
  replace: 'Данные пары изменены',
  add: 'Пара добавлена',
}

/** Пары с id `o-…` созданы изменением (доп. пара, перенесённая) — их можно только откатить. */
const isOverrideLesson = (lesson: Lesson) => lesson.id.startsWith('o-')

export function AdminSchedule({
  groups,
  groupId,
  schedule,
  days,
  slots,
  currentMinutes,
  token,
  onGroupChange,
  onWeekMove,
  onUnauthorized,
}: AdminScheduleProps) {
  const [targetMode, setTargetMode] = useState<'group' | 'stream'>('group')
  const [targetGroupIds, setTargetGroupIds] = useState<number[]>(groupId === null ? [] : [groupId])
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null)
  const [action, setAction] = useState<OverrideKind | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const [destinationDate, setDestinationDate] = useState('')
  const [timeChoice, setTimeChoice] = useState<TimeChoice>(1)
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [subject, setSubject] = useState('')
  const [lessonType, setLessonType] = useState('practice')
  const [teacher, setTeacher] = useState('')
  const [room, setRoom] = useState('')
  const [comment, setComment] = useState('')

  const lessonTypes = useLessonTypes()
  const catalog = useCatalog(token)
  const { create, remove } = useOverrideMutations(token)
  const busy = create.isPending || remove.isPending

  useEffect(() => {
    if (targetGroupIds.length === 0 && groupId !== null) setTargetGroupIds([groupId])
  }, [groupId, targetGroupIds.length])

  const activeGroups = groups.filter((group) => targetGroupIds.includes(group.id))
  const primaryGroup = groups.find((group) => group.id === groupId)
  const streamGroups = primaryGroup
    ? groups.filter((group) => group.course === primaryGroup.course)
    : groups
  const targetLabel = targetMode === 'stream'
    ? `Поток · ${activeGroups.length} группы`
    : primaryGroup?.name ?? 'Группа не выбрана'
  const requestGroupIds = targetMode === 'stream' ? targetGroupIds : groupId === null ? [] : [groupId]

  const resetForm = (day: Day, slot?: TimeSlot, lesson?: Lesson) => {
    setDestinationDate(day.date)
    if (lesson && lesson.slot === null) {
      setTimeChoice('custom')
    } else {
      setTimeChoice(slot?.number ?? lesson?.slot ?? slots[0]?.number ?? 1)
    }
    setCustomStart(lesson?.start_time ?? slot?.start_time ?? '')
    setCustomEnd(lesson?.end_time ?? slot?.end_time ?? '')
    setSubject(lesson?.subject ?? '')
    setLessonType(lesson?.type.code ?? 'practice')
    setTeacher(lesson?.teacher ?? '')
    setRoom(lesson?.room ?? '')
    setComment(lesson?.change?.comment ?? '')
    setError('')
  }

  const openLesson = (lesson: Lesson, day: Day) => {
    setSelectedCell({ kind: 'lesson', lesson, day })
    setAction(null)
    resetForm(day, undefined, lesson)
  }

  const openEmptySlot = (day: Day, slot: TimeSlot) => {
    setSelectedCell({ kind: 'empty', day, slot })
    setAction('add')
    resetForm(day, slot)
  }

  const closeDialog = () => {
    setSelectedCell(null)
    setAction(null)
    setError('')
  }

  const chooseTargetGroup = (id: number) => {
    setTargetGroupIds([id])
    onGroupChange(id)
  }

  const toggleStreamGroup = (id: number) => {
    const next = targetGroupIds.includes(id)
      ? targetGroupIds.filter((groupId) => groupId !== id)
      : [...targetGroupIds, id]

    if (next.length === 0) return
    setTargetGroupIds(next)
    if (!next.includes(groupId ?? -1)) onGroupChange(next[0])
  }

  const handleError = (reason: unknown) => {
    if (reason instanceof ApiError && reason.status === 401) {
      onUnauthorized()
      return
    }
    setError((reason as Error).message)
  }

  const buildRequest = (kind: OverrideKind): OverrideInput | null => {
    if (!selectedCell) return null
    const lesson = selectedCell.kind === 'lesson' ? selectedCell.lesson : null
    const body: OverrideInput = {
      group_ids: requestGroupIds,
      kind,
      date: kind === 'add' ? destinationDate : selectedCell.day.date,
      source_lesson_id: lesson ? Number(lesson.id.slice(2)) : null,
      comment: comment.trim() || null,
    }
    if (kind === 'cancel') return body

    if (kind === 'move') body.target_date = destinationDate
    if (timeChoice === 'custom') {
      body.start_time = customStart
      body.end_time = customEnd
    } else {
      body.slot = timeChoice
    }
    body.subject = subject.trim()
    body.lesson_type = lessonType
    body.teacher = teacher.trim()
    body.room = room.trim()
    return body
  }

  const submit = async () => {
    if (!action) return
    const body = buildRequest(action)
    if (!body) return
    setError('')
    try {
      await create.mutateAsync(body)
      const names = activeGroups.length && targetMode === 'stream'
        ? activeGroups.map((group) => group.name).join(', ')
        : primaryGroup?.name ?? ''
      setNotice(`${DONE_LABELS[action]} · ${names}. Студенты уже видят изменение.`)
      closeDialog()
    } catch (reason) {
      handleError(reason)
    }
  }

  const revert = async (lesson: Lesson) => {
    if (!lesson.change) return
    setError('')
    try {
      const result = await remove.mutateAsync({ id: lesson.change.override_id, batch: targetMode === 'stream' })
      setNotice(`Изменение отменено${result.deleted > 1 ? ` для ${result.deleted} пар потока` : ''}, пара вернулась к постоянному расписанию.`)
      closeDialog()
    } catch (reason) {
      handleError(reason)
    }
  }

  const customTimeInvalid = timeChoice === 'custom' && (!customStart || !customEnd || customEnd <= customStart)
  const formInvalid = action !== 'cancel' && (!subject.trim() || !destinationDate || customTimeInvalid)
  const selectedLesson = selectedCell?.kind === 'lesson' ? selectedCell.lesson : null

  return (
    <section className="admin-schedule">
      <div className="admin-schedule-heading">
        <div>
          <span className="eyebrow">АДМИНИСТРИРОВАНИЕ</span>
          <h1>Расписание</h1>
          <p className="muted">Выберите группу или поток, затем занятие в календаре.</p>
        </div>
      </div>

      <div className="admin-target-tabs" aria-label="Кого изменить">
        <button
          className={targetMode === 'group' ? 'active' : ''}
          onClick={() => {
            setTargetMode('group')
            if (groupId !== null) setTargetGroupIds([groupId])
          }}
        >Одна группа</button>
        <button
          className={targetMode === 'stream' ? 'active' : ''}
          onClick={() => setTargetMode('stream')}
        >Поток</button>
      </div>

      {targetMode === 'group' ? (
        <label className="admin-field">
          <span>Группа</span>
          <select
            className="select-field"
            value={groupId ?? ''}
            onChange={(event) => chooseTargetGroup(Number(event.target.value))}
          >
            {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
          </select>
        </label>
      ) : (
        <fieldset className="stream-groups">
          <legend>Группы потока</legend>
          {streamGroups.map((group) => (
            <label key={group.id}>
              <input
                type="checkbox"
                checked={targetGroupIds.includes(group.id)}
                onChange={() => toggleStreamGroup(group.id)}
              />
              <span>{group.name}</span>
            </label>
          ))}
        </fieldset>
      )}

      <div className="admin-week-heading">
        <div>
          <span className="eyebrow">{schedule ? `${dayLabel(schedule.week.start_date)} — ${dayLabel(schedule.week.end_date)}` : 'Расписание недели'}</span>
          <strong>Неделя {schedule?.week.number ?? '—'} · {targetLabel}</strong>
        </div>
        <div>
          <button
            className="icon-button outlined"
            aria-label="Предыдущая неделя"
            disabled={schedule?.week.prev == null}
            onClick={() => onWeekMove(-1)}
          ><ChevronLeft size={17} /></button>
          <button
            className="icon-button outlined"
            aria-label="Следующая неделя"
            disabled={schedule?.week.next == null}
            onClick={() => onWeekMove(1)}
          ><ChevronRight size={17} /></button>
        </div>
      </div>

      {notice && <div className="admin-draft-notice"><CalendarDays size={16} />{notice}</div>}
      {schedule
        ? <WeekGrid
            days={days}
            slots={slots}
            currentMinutes={currentMinutes}
            onLessonClick={openLesson}
            onEmptySlotClick={openEmptySlot}
          />
        : <div className="state-note">Загружаем расписание группы…</div>}

      {catalog.data && <>
        <datalist id="admin-subjects">{catalog.data.subjects.map((name) => <option key={name} value={name} />)}</datalist>
        <datalist id="admin-teachers">{catalog.data.teachers.map((name) => <option key={name} value={name} />)}</datalist>
        <datalist id="admin-rooms">{catalog.data.rooms.map((name) => <option key={name} value={name} />)}</datalist>
      </>}

      {selectedCell && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) closeDialog()
        }}>
          <section className="confirm-modal admin-edit-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-dialog-title">
            <button className="modal-close" aria-label="Закрыть" onClick={closeDialog}><X size={18} /></button>
            <span className="eyebrow">{targetLabel}</span>
            <h2 id="admin-dialog-title">
              {action ? ACTION_TITLES[action] : 'Изменить пару'}
            </h2>

            {selectedLesson && (
              <div className="admin-selected-lesson">
                <strong>{selectedLesson.subject}</strong>
                <span>{dayLabel(selectedCell.day.date)} · {selectedLesson.start_time}–{selectedLesson.end_time}</span>
                <span>{selectedLesson.type.name}{selectedLesson.teacher ? ` · ${selectedLesson.teacher}` : ''}{selectedLesson.room ? ` · ${selectedLesson.room}` : ''}</span>
                {changeDetails(selectedLesson).map((line) => <span className="admin-change-line" key={line}>{line}</span>)}
              </div>
            )}

            {selectedLesson && !action && (
              <>
                {selectedLesson.change && (
                  <button className="button button-secondary full" disabled={busy} onClick={() => revert(selectedLesson)}>
                    {targetMode === 'stream' ? 'Отменить изменение для потока' : 'Отменить изменение'}
                  </button>
                )}
                {isOverrideLesson(selectedLesson)
                  ? <p className="admin-dialog-hint">
                      Эта пара появилась из-за изменения. Отмена изменения уберёт её
                      {selectedLesson.status === 'moved_in' ? ' и вернёт исходную пару на прежнее место' : ''}.
                    </p>
                  : <>
                    <button className="button button-secondary full" onClick={() => setAction('cancel')}>Отменить пару</button>
                    <button className="button button-secondary full" onClick={() => setAction('replace')}>Заменить аудиторию, преподавателя…</button>
                    <button className="button button-primary full" onClick={() => setAction('move')}>Перенести пару</button>
                    {selectedLesson.change && <p className="admin-dialog-hint">Новое действие заменит текущее изменение этой пары.</p>}
                  </>}
              </>
            )}

            {action && action !== 'cancel' && (
              <>
                {action === 'move' && <p className="admin-dialog-hint">Исходная пара будет помечена как перенесённая, новая появится в выбранные дату и время.</p>}
                {action !== 'replace' && (
                  <label className="admin-field">
                    <span>{action === 'move' ? 'Новая дата' : 'Дата'}</span>
                    <input
                      className="text-field"
                      type="date"
                      value={destinationDate}
                      onChange={(event) => setDestinationDate(event.target.value)}
                    />
                  </label>
                )}
                <label className="admin-field">
                  <span>Время пары</span>
                  <select
                    className="select-field"
                    value={timeChoice}
                    onChange={(event) => setTimeChoice(event.target.value === 'custom' ? 'custom' : Number(event.target.value))}
                  >
                    {slots.map((slot) => <option key={slot.number} value={slot.number}>{slot.number} пара · {slot.start_time}–{slot.end_time}</option>)}
                    <option value="custom">Своё время (вне сетки)</option>
                  </select>
                </label>
                {timeChoice === 'custom' && (
                  <div className="admin-time-row">
                    <label className="admin-field">
                      <span>Начало</span>
                      <input className="text-field" type="time" value={customStart} onChange={(event) => setCustomStart(event.target.value)} />
                    </label>
                    <label className="admin-field">
                      <span>Конец</span>
                      <input className="text-field" type="time" value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} />
                    </label>
                  </div>
                )}
                <label className="admin-field">
                  <span>Дисциплина</span>
                  <input className="text-field" list="admin-subjects" value={subject} onChange={(event) => setSubject(event.target.value)} />
                </label>
                <label className="admin-field">
                  <span>Тип занятия</span>
                  <select className="select-field" value={lessonType} onChange={(event) => setLessonType(event.target.value)}>
                    {(lessonTypes.data ?? []).map((type) => <option key={type.code} value={type.code}>{type.name}</option>)}
                  </select>
                </label>
                <label className="admin-field">
                  <span>Преподаватель</span>
                  <input className="text-field" list="admin-teachers" value={teacher} onChange={(event) => setTeacher(event.target.value)} />
                </label>
                <label className="admin-field">
                  <span>Аудитория</span>
                  <input className="text-field" list="admin-rooms" value={room} onChange={(event) => setRoom(event.target.value)} />
                </label>
                {targetMode === 'stream' && action !== 'add' && (
                  <p className="admin-dialog-hint">Неизменённые поля у каждой группы потока останутся своими.</p>
                )}
              </>
            )}

            {action && (
              <>
                <label className="admin-field">
                  <span>Комментарий для студентов</span>
                  <input
                    className="text-field"
                    placeholder="Например: преподаватель на конференции"
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                  />
                </label>
                {action === 'cancel' && selectedLesson && (
                  <p>Пара «{selectedLesson.subject}» будет отменена для: {targetLabel}.</p>
                )}
              </>
            )}

            {error && <p className="form-error" role="alert">{error}</p>}

            {action && (
              <>
                <button className="button button-primary full" disabled={busy || formInvalid} onClick={submit}>
                  {busy ? 'Сохраняем…' : SUBMIT_LABELS[action]}
                </button>
                {selectedLesson && (
                  <button className="quiet-link centered" onClick={() => { setAction(null); setError('') }}>Назад к выбору действия</button>
                )}
              </>
            )}

          </section>
        </div>
      )}
    </section>
  )
}
