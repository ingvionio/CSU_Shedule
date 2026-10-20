import {
  ArrowLeft,
  CalendarDays,
  Clock3,
  FileSpreadsheet,
  MapPin,
  Menu,
  UserRound,
} from 'lucide-react'
import type { Day, Lesson, View } from './types'
import { lessonTimes } from './scheduleData'

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
  onMenu: () => void
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
      <button className="icon-button" aria-label="Переключить режим" onClick={onMenu}><Menu size={20} /></button>
    </header>
  )
}

export function LessonCard({ lesson }: { lesson: Lesson }) {
  return (
    <article className={`lesson-card ${lesson.status ?? ''}`}>
      <div className="lesson-time"><Clock3 size={14} /><span>{lesson.time}</span></div>
      <div className="lesson-main">
        <div className="lesson-heading">
          <h3>{lesson.subject}</h3>
          {lesson.status === 'changed' && <span className="badge badge-changed">Изменено</span>}
          {lesson.status === 'cancelled' && <span className="badge badge-cancelled">Отменено</span>}
        </div>
        {lesson.status === 'changed' && lesson.previousTime && (
          <p className="change-note">
            Было {lesson.previousTime}{lesson.validUntil ? ` · действует до ${lesson.validUntil}` : ''}
          </p>
        )}
        <div className="lesson-meta">
          <span>{lesson.kind}</span>
          <span><UserRound size={13} />{lesson.teacher}</span>
          <span><MapPin size={13} />Ауд. {lesson.room}</span>
        </div>
      </div>
    </article>
  )
}

export function DaySchedule({ day }: { day: Day }) {
  return (
    <section className="day-section">
      <div className="day-heading">
        <div><h2>{day.name}</h2><span>{day.date}</span></div>
        <span className="day-count">{day.lessons.length ? `${day.lessons.length} пары` : 'Нет пар'}</span>
      </div>
      {day.lessons.length
        ? <div className="lesson-list">
          {day.lessons.map((lesson) => (
            <LessonCard key={`${day.date}-${lesson.time}-${lesson.subject}`} lesson={lesson} />
          ))}
        </div>
        : <div className="empty-day">Занятий нет</div>}
    </section>
  )
}

export function WeekGrid({
  days,
  todayIndex,
  currentMinutes,
}: {
  days: Day[]
  todayIndex: number
  currentMinutes: number
}) {
  const lineVisible = todayIndex >= 0 && currentMinutes >= 480 && currentMinutes <= 1285
  const lineTop = ((currentMinutes - 480) / (1285 - 480)) * 100

  return (
    <div className="week-grid-scroll">
      <div className="week-grid">
        <div className="grid-corner" />
        {days.map((day, index) => (
          <div className={`grid-day ${index === todayIndex ? 'today' : ''}`} key={day.date}>
            <b>{['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'][index]}</b>
            <span>{day.date.split(' ')[0]}</span>
          </div>
        ))}

        {lessonTimes.map((time, row) => (
          <div className="grid-time" key={time} style={{ gridRow: row + 2, gridColumn: 1 }}>
            {time.slice(0, 5)}
          </div>
        ))}
        {days.map((day, column) => lessonTimes.map((time, row) => (
          <div className="grid-cell" key={`${day.date}-${time}`} style={{ gridColumn: column + 2, gridRow: row + 2 }} />
        )))}
        {days.map((day, column) => day.lessons.map((lesson, index) => {
          const hour = Number(lesson.time.slice(0, 2))
          const minute = Number(lesson.time.slice(3, 5))
          const row = Math.max(0, Math.min(7, lessonTimes.findIndex((slot) => (
            Number(slot.slice(0, 2)) * 60 + Number(slot.slice(3, 5)) >= hour * 60 + minute
          ))))

          return (
            <div
              key={`${day.date}-${lesson.subject}-${index}`}
              className={`grid-lesson ${lesson.status ?? ''}`}
              style={{ gridColumn: column + 2, gridRow: row + 2 }}
              title={`${lesson.time} · ${lesson.subject} · ${lesson.teacher} · ауд. ${lesson.room}`}
            >
              <b>{lesson.time.slice(0, 5)}</b>
              <span>{lesson.subject}</span>
              <small>{lesson.kind}</small>
              <small>{lesson.teacher} · {lesson.room}</small>
              {lesson.status === 'changed' && <em>Изменено</em>}
              {lesson.status === 'cancelled' && <em>Отменено</em>}
            </div>
          )
        }))}
        {lineVisible && (
          <div className="current-time-track" style={{ gridColumn: todayIndex + 2, gridRow: '2 / span 8' }}>
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
  const admin = ['admin', 'change', 'preview', 'excel'].includes(view)
  const items = admin
    ? [
      { label: 'Обзор', icon: CalendarDays, target: 'admin' as View },
      { label: 'Изменения', icon: Clock3, target: 'change' as View },
      { label: 'Excel', icon: FileSpreadsheet, target: 'excel' as View },
    ]
    : [
      { label: 'Расписание', icon: CalendarDays, target: 'day' as View },
      { label: 'Группа', icon: UserRound, target: 'group' as View },
    ]

  return (
    <nav className={`bottom-nav ${admin ? 'admin-nav' : 'student-nav'}`}>
      {items.map(({ label, icon: Icon, target }) => (
        <button
          key={label}
          className={`nav-item ${(view === target || (!admin && target === 'day' && view === 'week')) ? 'active' : ''}`}
          onClick={() => onNavigate(target)}
        >
          <Icon size={18} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  )
}
