import { useEffect, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, X } from 'lucide-react'

import { WeekGrid, dayLabel } from '../../ScheduleComponents'
import type { Day, Group, Lesson, TimeSlot, WeekSchedule } from '../../types'

type ChangeAction = 'cancel' | 'move' | 'add'
type SelectedCell =
  | { kind: 'lesson'; day: Day; lesson: Lesson }
  | { kind: 'empty'; day: Day; slot: TimeSlot }

type AdminScheduleProps = {
  groups: Group[]
  groupId: number | null
  schedule?: WeekSchedule
  days: Day[]
  slots: TimeSlot[]
  currentMinutes: number
  onGroupChange: (id: number) => void
  onWeekMove: (delta: number) => void
  onDaysChange: (days: Day[], groupIds: number[]) => void
}

const NEW_LESSON_TYPES = ['Лекция', 'Практическое занятие', 'Лабораторная работа', 'Семинар']

export function AdminSchedule({
  groups,
  groupId,
  schedule,
  days,
  slots,
  currentMinutes,
  onGroupChange,
  onWeekMove,
  onDaysChange,
}: AdminScheduleProps) {
  const [targetMode, setTargetMode] = useState<'group' | 'stream'>('group')
  const [targetGroupIds, setTargetGroupIds] = useState<number[]>(groupId === null ? [] : [groupId])
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null)
  const [action, setAction] = useState<ChangeAction | null>(null)
  const [draftNotice, setDraftNotice] = useState('')
  const [destinationDate, setDestinationDate] = useState('')
  const [destinationSlot, setDestinationSlot] = useState<number | ''>('')
  const [subject, setSubject] = useState('')
  const [lessonType, setLessonType] = useState(NEW_LESSON_TYPES[0])
  const [teacher, setTeacher] = useState('')
  const [room, setRoom] = useState('')

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
    : activeGroups[0]?.name ?? 'Группа не выбрана'
  const lessonTypes = [...new Set([
    ...days.flatMap((day) => day.lessons.map((lesson) => lesson.type.name)),
    ...NEW_LESSON_TYPES,
  ])]

  const resetDraftFields = (day: Day, slot?: TimeSlot, lesson?: Lesson) => {
    setDestinationDate(day.date)
    setDestinationSlot(slot?.number ?? lesson?.slot ?? slots[0]?.number ?? '')
    setSubject(lesson?.subject ?? '')
    setLessonType(lesson?.type.name ?? NEW_LESSON_TYPES[0])
    setTeacher(lesson?.teacher ?? '')
    setRoom(lesson?.room ?? '')
  }

  const openLesson = (lesson: Lesson, day: Day) => {
    setSelectedCell({ kind: 'lesson', lesson, day })
    setAction(null)
    const sourceSlot = slots.find((slot) => slot.number === lesson.slot)
      ?? slots.find((slot) => slot.end_time >= lesson.start_time)
      ?? slots[0]
    resetDraftFields(day, sourceSlot, lesson)
  }

  const openEmptySlot = (day: Day, slot: TimeSlot) => {
    setSelectedCell({ kind: 'empty', day, slot })
    setAction('add')
    resetDraftFields(day, slot)
  }

  const closeDialog = () => {
    setSelectedCell(null)
    setAction(null)
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

  const prepareDraft = () => {
    const selectedGroups = activeGroups.map((group) => group.name).join(', ')
    const source = selectedCell?.kind === 'lesson'
      ? `${selectedCell.lesson.subject}, ${dayLabel(selectedCell.day.date)} ${selectedCell.lesson.start_time}`
      : ''
    const destination = `${subject.trim()}, ${dayLabel(destinationDate)} · ${slots.find((slot) => slot.number === destinationSlot)?.start_time ?? ''}`
    const result = action === 'cancel'
      ? `Отмена: ${source}.`
      : action === 'move'
        ? `Перенос: ${source} → ${destination}; исходная пара будет отменена.`
        : `Добавление: ${destination}.`

    const sourceCell = selectedCell?.kind === 'lesson' ? selectedCell : null
    const selectedSlot = slots.find((slot) => slot.number === destinationSlot)
    const nextDays = days.map((day) => {
      let lessons = day.lessons.map((lesson) => {
        if (!sourceCell || day.date !== sourceCell.day.date || lesson.id !== sourceCell.lesson.id || action === 'add') return lesson
        return {
          ...lesson,
          status: action === 'move' ? 'moved_out' as const : 'cancelled' as const,
          change: { kind: action === 'move' ? 'move' as const : 'cancel' as const, comment: null, original: null, moved_to: null, moved_from: null },
        }
      })

      if (selectedSlot && day.date === destinationDate && (action === 'add' || action === 'move')) {
        lessons = [...lessons, {
          id: `draft-${Date.now()}`,
          start_time: selectedSlot.start_time,
          end_time: selectedSlot.end_time,
          slot: selectedSlot.number,
          subject: subject.trim(),
          type: { code: lessonType.toLowerCase().replace(/\s+/g, '_'), name: lessonType },
          room: room.trim() || null,
          teacher: teacher.trim() || null,
          subgroup: null,
          status: action === 'move' ? 'moved_in' as const : 'added' as const,
          change: { kind: action === 'move' ? 'move' as const : 'add' as const, comment: null, original: null, moved_to: null, moved_from: null },
        }].sort((left, right) => left.start_time.localeCompare(right.start_time))
      }
      return { ...day, lessons }
    })

    onDaysChange(nextDays, targetGroupIds.length ? targetGroupIds : groupId === null ? [] : [groupId])
    setDraftNotice(`${result} Для ${targetLabel}${selectedGroups ? ` (${selectedGroups})` : ''}. Изменение сразу видно в расписании этой сессии.`)
    closeDialog()
  }

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

      {draftNotice && <div className="admin-draft-notice"><CalendarDays size={16} />{draftNotice}</div>}
      {schedule
        ? <WeekGrid
            days={days}
            slots={slots}
            currentMinutes={currentMinutes}
            onLessonClick={openLesson}
            onEmptySlotClick={openEmptySlot}
          />
        : <div className="state-note">Загружаем расписание группы…</div>}

      {selectedCell && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) closeDialog()
        }}>
          <section className="confirm-modal admin-edit-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-dialog-title">
            <button className="modal-close" aria-label="Закрыть" onClick={closeDialog}><X size={18} /></button>
            <span className="eyebrow">{targetLabel}</span>
            <h2 id="admin-dialog-title">
              {selectedCell.kind === 'empty' ? 'Добавить пару' : 'Изменить пару'}
            </h2>

            {selectedCell.kind === 'lesson' && !action && (
              <>
                <div className="admin-selected-lesson">
                  <strong>{selectedCell.lesson.subject}</strong>
                  <span>{dayLabel(selectedCell.day.date)} · {selectedCell.lesson.start_time}–{selectedCell.lesson.end_time}</span>
                  <span>{selectedCell.lesson.type.name}{selectedCell.lesson.room ? ` · ${selectedCell.lesson.room}` : ''}</span>
                </div>
                <button className="button button-secondary full" onClick={() => setAction('cancel')}>Отменить пару</button>
                <button className="button button-primary full" onClick={() => setAction('move')}>Перенести пару</button>
                <p className="admin-dialog-hint">Перенос отменит исходную пару и создаст новую в выбранном времени.</p>
              </>
            )}

            {selectedCell.kind === 'lesson' && action === 'cancel' && (
              <>
                <p>Пара «{selectedCell.lesson.subject}» будет отменена для: {targetLabel}.</p>
                <button className="button button-primary full" onClick={prepareDraft}>Подготовить отмену</button>
                <button className="quiet-link centered" onClick={() => setAction(null)}>Назад к выбору действия</button>
              </>
            )}

            {((selectedCell.kind === 'lesson' && action === 'move') || selectedCell.kind === 'empty') && (
              <>
                {selectedCell.kind === 'lesson' && <p className="admin-dialog-hint">Исходная пара будет отменена, новая — добавлена в выбранные дату и время.</p>}
                <label className="admin-field">
                  <span>Дата</span>
                  <select className="select-field" value={destinationDate} onChange={(event) => setDestinationDate(event.target.value)}>
                    {days.map((day) => <option key={day.date} value={day.date}>{dayLabel(day.date)}</option>)}
                  </select>
                </label>
                <label className="admin-field">
                  <span>Время пары</span>
                  <select className="select-field" value={destinationSlot} onChange={(event) => setDestinationSlot(Number(event.target.value))}>
                    {slots.map((slot) => <option key={slot.number} value={slot.number}>{slot.number} пара · {slot.start_time}–{slot.end_time}</option>)}
                  </select>
                </label>
                <label className="admin-field">
                  <span>Дисциплина</span>
                  <input className="text-field" value={subject} onChange={(event) => setSubject(event.target.value)} />
                </label>
                <label className="admin-field">
                  <span>Тип занятия</span>
                  <select className="select-field" value={lessonType} onChange={(event) => setLessonType(event.target.value)}>
                    {lessonTypes.map((type) => <option key={type}>{type}</option>)}
                  </select>
                </label>
                <label className="admin-field">
                  <span>Преподаватель</span>
                  <input className="text-field" value={teacher} onChange={(event) => setTeacher(event.target.value)} />
                </label>
                <label className="admin-field">
                  <span>Аудитория</span>
                  <input className="text-field" value={room} onChange={(event) => setRoom(event.target.value)} />
                </label>
                <button className="button button-primary full" disabled={!subject.trim()} onClick={prepareDraft}>
                  {selectedCell.kind === 'empty' ? 'Подготовить добавление' : 'Подготовить перенос'}
                </button>
              </>
            )}
          </section>
        </div>
      )}
    </section>
  )
}
