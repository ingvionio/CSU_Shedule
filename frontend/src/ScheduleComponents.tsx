import { ArrowLeft, CalendarDays, Clock3, MapPin, Menu, MessageCircleQuestion, UserRound } from 'lucide-react'

import type { Day, Lesson, MovePoint, TimeSlot, View } from './types'

const WEEKDAY_NAMES = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
const WEEKDAY_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']

/** Пометки для статусов временных изменений. Для `regular` пометки нет. */
const STATUS_LABELS: Record<string, string> = {
  changed: 'Изменено',
  cancelled: 'Отменено',
  moved_out: 'Перенесено',
  moved_in: 'Перенос',
  added: 'Новое',
}

/** CSS-класс карточки: зачёркнутые отменённые и перенесённые с этого времени. */
function statusClass(status: string): string {
  if (status === 'cancelled' || status === 'moved_out') return 'cancelled'
  if (status === 'regular') return ''
  return 'changed'
}

export function dayLabel(date: string): string {
  return new Date(date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
}

/** «23 октября, 13:15–14:45» — куда или откуда перенесена пара. */
function pointLabel(point: MovePoint): string {
  return `${dayLabel(point.date)}, ${point.start_time}–${point.end_time}`
}

/** Прежние значения изменённой пары: «ауд. 132Б», «13:15–14:45»… */
function originalLabel(lesson: Lesson): string | null {
  const original = lesson.change?.original
  if (!original) return null
  const parts: string[] = []
  if ('start_time' in original || 'end_time' in original) {
    parts.push(`${original.start_time ?? lesson.start_time}–${original.end_time ?? lesson.end_time}`)
  }
  if ('subject' in original) parts.push(String(original.subject))
  if ('type' in original) parts.push((original.type as { name: string }).name)
  if ('teacher' in original) parts.push(original.teacher ? String(original.teacher) : 'без преподавателя')
  if ('room' in original) parts.push(original.room ? `ауд. ${original.room}` : 'без аудитории')
  return parts.length ? `Было: ${parts.join(', ')}` : null
}

/** Пояснения к изменённой паре для студента и админа. */
export function changeDetails(lesson: Lesson): string[] {
  const change = lesson.change
  if (!change) return []
  return [
    change.moved_to && `Перенесена на ${pointLabel(change.moved_to)}`,
    change.moved_from && `Перенесена с ${pointLabel(change.moved_from)}`,
    originalLabel(lesson),
    change.comment,
  ].filter((line): line is string => Boolean(line))
}

export function dayNumber(date: string): string {
  return String(new Date(date).getDate())
}

/**
 * Диапазон недели: «19–25 октября», а если неделя переходит в другой месяц —
 * «28 сентября – 4 октября». Месяц нужен в родительном падеже, поэтому
 * берётся из форматирования полной даты, а не из `{ month: 'long' }`.
 */
export function weekRangeLabel(start: string, end: string): string {
  const sameMonth = new Date(start).getMonth() === new Date(end).getMonth()
  return sameMonth
    ? `${dayNumber(start)}–${dayLabel(end)}`
    : `${dayLabel(start)} – ${dayLabel(end)}`
}

function minutesOf(time: string): number {
  const [hours, minutes] = time.split(':').map(Number)
  return hours * 60 + minutes
}

/**
 * Группирует пары дня по строкам сетки. В одну клетку может попасть несколько
 * пар (например, разные подгруппы) — тогда они показываются одна под другой,
 * а не накладываются друг на друга.
 */
function groupByRow(lessons: Lesson[], rowOf: (lesson: Lesson) => number): [number, Lesson[]][] {
  const byRow = new Map<number, Lesson[]>()
  for (const lesson of lessons) {
    const row = rowOf(lesson)
    byRow.set(row, [...(byRow.get(row) ?? []), lesson])
  }
  return [...byRow.entries()].sort(([a], [b]) => a - b)
}

export function Brand() {
  return <div className="brand" aria-label="Челябинский государственный университет">ЧелГУ</div>
}

export function Header({
  title,
  onBack,
  subtitle,
  onMenu,
}: {
  title: string
  onBack?: () => void
  subtitle?: string
  onMenu?: () => void
}) {
  return (
    <header className="topbar">
      {onBack
        ? <button className="icon-button" aria-label="Назад" onClick={onBack}><ArrowLeft size={20} /></button>
        : <Brand />}
      <div className="topbar-title">
        <strong>{title}</strong>
        {subtitle && <span>{subtitle}</span>}
      </div>
      {onMenu
        ? <button className="icon-button" aria-label="Меню" onClick={onMenu}><Menu size={20} /></button>
        : <span className="icon-button placeholder" aria-hidden="true" />}
    </header>
  )
}

/** Подпись времени: номер пары сверху, если она стоит по звонку, и время под ним. */
function LessonTime({ lesson }: { lesson: Lesson }) {
  return (
    <div className="lesson-time">
      <Clock3 size={14} />
      <span>
        {lesson.slot !== null && <b>{lesson.slot} пара</b>}
        <i>{lesson.start_time}–{lesson.end_time}</i>
      </span>
    </div>
  )
}

export function LessonCard({ lesson }: { lesson: Lesson }) {
  const label = STATUS_LABELS[lesson.status]

  return (
    <article className={`lesson-card ${statusClass(lesson.status)}`}>
      <LessonTime lesson={lesson} />
      <div className="lesson-main">
        <div className="lesson-heading">
          <h3>{lesson.subject}</h3>
          {label && (
            <span className={`badge ${lesson.status === 'cancelled' ? 'badge-cancelled' : 'badge-changed'}`}>
              {label}
            </span>
          )}
        </div>
        {changeDetails(lesson).map((line) => <p className="change-note" key={line}>{line}</p>)}
        <div className="lesson-meta">
          <span>{lesson.type.name}</span>
          {lesson.subgroup !== null && <span>{lesson.subgroup} подгруппа</span>}
          {lesson.teacher && <span><UserRound size={13} />{lesson.teacher}</span>}
          {lesson.room && <span><MapPin size={13} />{lesson.room === 'ФОК' ? 'ФОК' : `Ауд. ${lesson.room}`}</span>}
        </div>
      </div>
    </article>
  )
}

/** Склонение: 1 пара, 2 пары, 5 пар. */
function lessonsCount(count: number): string {
  if (count === 0) return 'Нет пар'
  const last = count % 10
  const tens = count % 100
  if (last === 1 && tens !== 11) return `${count} пара`
  if (last >= 2 && last <= 4 && (tens < 12 || tens > 14)) return `${count} пары`
  return `${count} пар`
}

export function DaySchedule({ day }: { day: Day }) {
  return (
    <section className="day-section">
      <div className="day-heading">
        <div>
          <h2>{WEEKDAY_NAMES[day.weekday - 1]}</h2>
          <span>{dayLabel(day.date)}</span>
        </div>
        <span className="day-count">{lessonsCount(day.lessons.length)}</span>
      </div>
      {day.lessons.length
        ? <div className="lesson-list">
          {day.lessons.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} />)}
        </div>
        : <div className="empty-day">Занятий нет</div>}
    </section>
  )
}

export function WeekGrid({
  days,
  slots,
  currentMinutes,
  onLessonClick,
  onEmptySlotClick,
}: {
  days: Day[]
  slots: TimeSlot[]
  currentMinutes: number
  onLessonClick?: (lesson: Lesson, day: Day) => void
  onEmptySlotClick?: (day: Day, slot: TimeSlot) => void
}) {
  const todayIndex = days.findIndex((day) => day.is_today)
  const gridStart = slots.length ? minutesOf(slots[0].start_time) : 0
  const gridEnd = slots.length ? minutesOf(slots[slots.length - 1].end_time) : 0
  const lineVisible = todayIndex >= 0 && currentMinutes >= gridStart && currentMinutes <= gridEnd
  const lineTop = gridEnd > gridStart ? ((currentMinutes - gridStart) / (gridEnd - gridStart)) * 100 : 0

  /** Строка сетки: номер пары, а для пары вне сетки — ближайший по времени слот. */
  const rowOf = (lesson: Lesson): number => {
    if (lesson.slot !== null) {
      const index = slots.findIndex((slot) => slot.number === lesson.slot)
      if (index >= 0) return index
    }
    const start = minutesOf(lesson.start_time)
    const nearest = slots.findIndex((slot) => minutesOf(slot.end_time) >= start)
    return nearest >= 0 ? nearest : Math.max(0, slots.length - 1)
  }

  return (
    <div className="week-grid-scroll">
      <div className="week-grid" style={{ gridTemplateRows: `auto repeat(${slots.length}, 1fr)` }}>
        <div className="grid-corner" />
        {days.map((day, index) => (
          <div className={`grid-day ${day.is_today ? 'today' : ''}`} key={day.date}>
            <b>{WEEKDAY_SHORT[index]}</b>
            <span>{dayNumber(day.date)}</span>
          </div>
        ))}

        {slots.map((slot, row) => (
          <div className="grid-time" key={slot.number} style={{ gridRow: row + 2, gridColumn: 1 }}>
            {slot.start_time}
          </div>
        ))}
        {days.map((day, column) => slots.map((slot, row) => (
          <div
            className="grid-cell"
            key={`${day.date}-${slot.number}`}
            style={{ gridColumn: column + 2, gridRow: row + 2 }}
          />
        )))}
        {days.map((day, column) => slots.map((slot, row) => {
          const lessons = groupByRow(day.lessons, rowOf).find(([lessonRow]) => lessonRow === row)?.[1] ?? []
          const canAdd = Boolean(onEmptySlotClick && lessons.length === 0)
          return <div
            className={`grid-slot ${canAdd ? 'grid-slot-empty' : ''}`}
            key={`${day.date}-${slot.number}`}
            style={{ gridColumn: column + 2, gridRow: row + 2 }}
            onClick={(event) => {
              if (event.target === event.currentTarget) onEmptySlotClick?.(day, slot)
            }}
            role={canAdd ? 'button' : undefined}
            tabIndex={canAdd ? 0 : undefined}
            aria-label={canAdd ? `Добавить пару: ${dayLabel(day.date)}, ${slot.start_time}` : undefined}
            onKeyDown={(event) => {
              if ((event.key === 'Enter' || event.key === ' ') && canAdd) {
                event.preventDefault()
                onEmptySlotClick?.(day, slot)
              }
            }}
          >
            {lessons.map((lesson) => (
              <div
                key={lesson.id}
                className={`grid-lesson ${statusClass(lesson.status)} ${onLessonClick ? 'grid-lesson-selectable' : ''}`}
                title={`${lesson.start_time}–${lesson.end_time} · ${lesson.subject} · ${lesson.type.name}`
                  + `${lesson.teacher ? ` · ${lesson.teacher}` : ''}${lesson.room ? ` · ауд. ${lesson.room}` : ''}`}
                role={onLessonClick ? 'button' : undefined}
                tabIndex={onLessonClick ? 0 : undefined}
                onClick={onLessonClick ? () => onLessonClick(lesson, day) : undefined}
                onKeyDown={onLessonClick ? (event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onLessonClick(lesson, day)
                  }
                } : undefined}
              >
                <b>{lesson.start_time}</b>
                <span>{lesson.subject}</span>
                <small>{lesson.type.name}{lesson.subgroup !== null ? ` · ${lesson.subgroup} п/гр` : ''}</small>
                <small>{[lesson.teacher, lesson.room].filter(Boolean).join(' · ')}</small>
                {STATUS_LABELS[lesson.status] && <em>{STATUS_LABELS[lesson.status]}</em>}
              </div>
            ))}
          </div>
        }))}
        {lineVisible && (
          <div
            className="current-time-track"
            style={{ gridColumn: todayIndex + 2, gridRow: `2 / span ${slots.length}` }}
          >
            <div className="current-time-line" style={{ top: `${lineTop}%` }} />
            <div className="current-time-label" style={{ top: `${lineTop}%` }}>
              {`${String(Math.floor(currentMinutes / 60)).padStart(2, '0')}:${String(currentMinutes % 60).padStart(2, '0')}`}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export function BottomNav({ view, onNavigate }: { view: View; onNavigate: (view: View) => void }) {
  const items = [
    { label: 'Расписание', icon: CalendarDays, target: 'day' as View },
    { label: 'Вопросы', icon: MessageCircleQuestion, target: 'feedback' as View },
    { label: 'Группа', icon: UserRound, target: 'group' as View },
  ]

  return (
    <nav className="bottom-nav student-nav">
      {items.map(({ label, icon: Icon, target }) => (
        <button
          key={label}
          className={`nav-item ${view === target || (target === 'day' && view === 'week') ? 'active' : ''}`}
          onClick={() => onNavigate(target)}
        >
          <Icon size={18} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  )
}
