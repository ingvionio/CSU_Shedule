import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'

import { clearAdminSession, readAdminSession, readSelectedGroup, writeAdminSession, writeSelectedGroup } from './api/cache'
import { useCurrentWeek, useGroups, useSchedule, useTimeSlots } from './api/queries'
import { BottomNav, DaySchedule, Header, WeekGrid, dayNumber, weekRangeLabel } from './ScheduleComponents'
import { AdminLogin } from './pages/admin/AdminLogin'
import { AdminFeedback } from './pages/admin/AdminFeedback'
import { AdminSchedule } from './pages/admin/AdminSchedule'
import { StudentFeedback } from './pages/feedback/StudentFeedback'
import type { AdminSession, Group, View } from './types'

const WEEKDAY_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
const COURSES = [1, 2, 3, 4]

/** Направление подготовки из названия группы: «ИТ1-ПрИб-11» -> «ПрИ», «ПИ 201» -> «ПИ». */
function directionOf(name: string): string {
  const match = name.match(/(ПрИ|ПИ|БИ)/)
  return match ? match[1] : name
}

export function App() {
  const [view, setView] = useState<View>('day')
  const [groupId, setGroupId] = useState<number | null>(() => readSelectedGroup())
  const [adminGroupId, setAdminGroupId] = useState<number | null>(null)
  const [weekNumber, setWeekNumber] = useState<number | null>(null)
  const [selectedDay, setSelectedDay] = useState(0)
  const [now, setNow] = useState(() => new Date())
  const [menuOpen, setMenuOpen] = useState(false)
  const [adminSession, setAdminSession] = useState<AdminSession | null>(() => readAdminSession())
  const [adminSection, setAdminSection] = useState<'schedule' | 'feedback'>('schedule')

  // Выбор группы на экране настройки.
  const [course, setCourse] = useState(1)
  const [direction, setDirection] = useState('ПИ')

  // Жесты и анимация переключения недель.
  const [slideDirection, setSlideDirection] = useState<'next' | 'prev'>('next')
  const [dragX, setDragX] = useState(0)
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef<{ x: number; y: number } | null>(null)
  const ignoreDateClick = useRef(false)

  const groups = useGroups()
  const timeSlots = useTimeSlots()
  const currentWeek = useCurrentWeek()
  const schedule = useSchedule(groupId, weekNumber)
  const adminSchedule = useSchedule(adminGroupId, weekNumber)

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000)
    return () => window.clearInterval(timer)
  }, [])

  // По умолчанию открывается текущая неделя.
  useEffect(() => {
    if (weekNumber === null && currentWeek.data) setWeekNumber(currentWeek.data.number)
  }, [currentWeek.data, weekNumber])

  // Пока группа не выбрана, показываем экран выбора.
  useEffect(() => {
    if (groupId === null && groups.data?.length) setView('group')
  }, [groupId, groups.data])

  useEffect(() => {
    if (view === 'admin' && adminGroupId === null && groups.data?.length) {
      setAdminGroupId(groupId ?? groups.data[0].id)
    }
  }, [view, adminGroupId, groupId, groups.data])

  const week = schedule.data?.week
  const days = schedule.data?.days ?? []
  const adminDays = adminSchedule.data?.days ?? []

  const loginAdmin = (session: AdminSession) => {
    writeAdminSession(session)
    setAdminSession(session)
  }

  const logoutAdmin = () => {
    clearAdminSession()
    setAdminSession(null)
    setMenuOpen(false)
  }

  // На текущей неделе открываем сегодняшний день.
  useEffect(() => {
    const todayIndex = days.findIndex((day) => day.is_today)
    if (todayIndex >= 0) setSelectedDay(todayIndex)
  }, [week?.number, days.length])

  const groupOptions = useMemo(
    () => (groups.data ?? []).filter((group) => group.course === course && directionOf(group.name) === direction),
    [groups.data, course, direction],
  )

  const directions = useMemo(() => {
    const available = (groups.data ?? []).filter((group) => group.course === course)
    return [...new Set(available.map((group) => directionOf(group.name)))]
  }, [groups.data, course])

  const selectedGroup: Group | undefined = (groups.data ?? []).find((group) => group.id === groupId)
  const currentMinutes = now.getHours() * 60 + now.getMinutes()

  const chooseGroup = (group: Group) => {
    setGroupId(group.id)
    writeSelectedGroup(group.id)
    setWeekNumber(currentWeek.data?.number ?? null)
    setView('day')
  }

  const moveWeek = (delta: number) => {
    const target = delta > 0 ? week?.next : week?.prev
    if (target == null) return
    setSlideDirection(delta > 0 ? 'next' : 'prev')
    setWeekNumber(target)
  }

  const handleDragStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    dragStart.current = { x: event.clientX, y: event.clientY }
  }

  const handleDragMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragStart.current) return
    const dx = event.clientX - dragStart.current.x
    const dy = event.clientY - dragStart.current.y
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 8) {
      event.preventDefault()
      if (!dragging) event.currentTarget.setPointerCapture(event.pointerId)
      setDragging(true)
      setDragX(dx)
    }
  }

  const handleDragEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragStart.current) return
    const dx = event.clientX - dragStart.current.x
    const dy = event.clientY - dragStart.current.y
    if (Math.abs(dx) > 65 && Math.abs(dx) > Math.abs(dy) * 1.2) {
      ignoreDateClick.current = true
      moveWeek(dx < 0 ? 1 : -1)
      window.setTimeout(() => { ignoreDateClick.current = false }, 0)
    }
    dragStart.current = null
    setDragging(false)
    setDragX(0)
  }

  const nav = (next: View) => {
    setView(next)
    setMenuOpen(false)
  }

  const moveAdminWeek = (delta: number) => {
    const target = delta > 0 ? adminSchedule.data?.week.next : adminSchedule.data?.week.prev
    if (target != null) setWeekNumber(target)
  }

  if (groups.isLoading && !groups.data) {
    return <div className="app-shell"><div className="state-note">Загружаем расписание…</div></div>
  }

  if (groups.isError && !groups.data) {
    return (
      <div className="app-shell">
        <div className="state-note error-note">
          <span>{(groups.error as Error).message}</span>
          <button className="button button-secondary" onClick={() => groups.refetch()}>
            <RefreshCw size={16} />Повторить
          </button>
        </div>
      </div>
    )
  }

  return <div className="app-shell">
    <Header
      title={view === 'group'
        ? 'Выберите группу'
        : view === 'admin' ? 'Администрирование' : view === 'feedback' ? 'Вопросы' : 'Расписание'}
      subtitle={view === 'group'
        ? 'Группа сохранится на этом устройстве'
        : view === 'admin'
          ? adminSection === 'feedback' ? 'Обращения студентов' : 'Управление расписанием'
          : `Институт ИТ · ${selectedGroup?.name ?? ''}`}
      onBack={view === 'group' && groupId !== null ? () => nav('day') : undefined}
      onMenu={() => setMenuOpen((open) => !open)}
    />
    {menuOpen && <div className="role-switch-menu">
      <span>РЕЖИМ</span>
      <button onClick={() => nav('day')}>Студенческое расписание</button>
      <button onClick={() => nav('admin')}>Администрирование расписания</button>
      {adminSession && <button onClick={logoutAdmin}>Выйти из админки</button>}
    </div>}

    <main className="content">
      {view === 'group' && <section className="screen-card selection-screen">
        <div className="eyebrow">ПЕРВЫЙ ШАГ</div>
        <h1>Выберите свою группу</h1>
        <p className="muted">Группа сохранится на этом устройстве.</p>

        <label className="field-label">Институт</label>
        <button className="select-field" disabled>
          Институт информационных технологий <ChevronDown size={17} />
        </button>

        <label className="field-label">Курс</label>
        <div className="choice-row">
          {COURSES.map((item) => (
            <button
              key={item}
              className={`choice ${course === item ? 'selected' : ''}`}
              onClick={() => setCourse(item)}
            >{item}</button>
          ))}
        </div>

        <label className="field-label">Направление</label>
        <div className="choice-row">
          {directions.map((item) => (
            <button
              key={item}
              className={`choice ${direction === item ? 'selected' : ''}`}
              onClick={() => setDirection(item)}
            >{item}</button>
          ))}
        </div>

        <label className="field-label">Группа</label>
        {groupOptions.length
          ? <div className="group-grid">
            {groupOptions.map((group) => (
              <button
                key={group.id}
                className={`group-option ${groupId === group.id ? 'selected' : ''}`}
                onClick={() => chooseGroup(group)}
              >{group.name}</button>
            ))}
          </div>
          : <div className="empty-day">На этом направлении групп нет</div>}
      </section>}

      {view === 'feedback' && <StudentFeedback groupId={groupId} />}

      {groupId === null && view !== 'group' && view !== 'feedback' && view !== 'admin' && (
        <div className="state-note">Выберите группу, чтобы увидеть расписание.</div>
      )}

      {groupId !== null && (view === 'day' || view === 'week') && <>
        <section className="schedule-intro">
          <div className="week-line">
            <div>
              <span className="eyebrow">
                {week ? weekRangeLabel(week.start_date, week.end_date) : ' '}
              </span>
              <h1>
                Неделя {week?.number ?? '—'}{' '}
                <span className="parity">{week?.parity === 'odd' ? 'нечётная' : week?.parity === 'even' ? 'чётная' : ''}</span>
              </h1>
            </div>
            <button
              className="icon-button outlined"
              aria-label="Предыдущая неделя"
              disabled={week?.prev == null}
              onClick={() => moveWeek(-1)}
            ><ChevronLeft size={18} /></button>
            <button
              className="icon-button outlined"
              aria-label="Следующая неделя"
              disabled={week?.next == null}
              onClick={() => moveWeek(1)}
            ><ChevronRight size={18} /></button>
          </div>
          <div className="segmented">
            <button className={view === 'day' ? 'active' : ''} onClick={() => setView('day')}>На день</button>
            <button className={view === 'week' ? 'active' : ''} onClick={() => setView('week')}>На неделю</button>
          </div>
        </section>

        {schedule.isError && (
          <div className="state-note error-note">
            <span>{(schedule.error as Error).message}</span>
            <button className="button button-secondary" onClick={() => schedule.refetch()}>
              <RefreshCw size={16} />Повторить
            </button>
          </div>
        )}

        {!schedule.data && schedule.isLoading && <div className="state-note">Загружаем неделю…</div>}

        {schedule.data && (view === 'week'
          ? <WeekGrid days={days} slots={timeSlots.data ?? []} currentMinutes={currentMinutes} />
          : <>
            <div className="week-picker-clip">
              <div
                key={week?.number}
                className={`date-strip week-picker ${dragging ? 'dragging' : `slide-${slideDirection}`}`}
                style={dragging ? { transform: `translateX(${dragX}px)` } : undefined}
                onPointerDown={handleDragStart}
                onPointerMove={handleDragMove}
                onPointerUp={handleDragEnd}
                onPointerCancel={handleDragEnd}
              >
                {days.map((day, index) => (
                  <button
                    className={`date-cell ${selectedDay === index ? 'active' : ''} ${day.is_today ? 'today' : ''}`}
                    key={day.date}
                    onClick={() => { if (!ignoreDateClick.current) setSelectedDay(index) }}
                  >
                    <span>{WEEKDAY_SHORT[index]}</span>
                    <strong>{dayNumber(day.date)}</strong>
                  </button>
                ))}
              </div>
            </div>
            {days[selectedDay] && <DaySchedule day={days[selectedDay]} />}
          </>)}

        {schedule.data && schedule.isStale && !navigator.onLine && (
          <div className="state-note muted">
            Показано сохранённое расписание · обновлено{' '}
            {new Date(schedule.data.generated_at).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}
          </div>
        )}
      </>}

      {view === 'admin' && !adminSession && <AdminLogin onLogin={loginAdmin} />}

      {view === 'admin' && adminSession && (
        <div className="admin-target-tabs admin-sections" aria-label="Раздел админки">
          <button
            className={adminSection === 'schedule' ? 'active' : ''}
            onClick={() => setAdminSection('schedule')}
          >Расписание</button>
          <button
            className={adminSection === 'feedback' ? 'active' : ''}
            onClick={() => setAdminSection('feedback')}
          >Обращения</button>
        </div>
      )}

      {view === 'admin' && adminSession && adminSection === 'feedback' && (
        <AdminFeedback token={adminSession.token} onUnauthorized={logoutAdmin} />
      )}

      {view === 'admin' && adminSession && adminSection === 'schedule' && (
        <AdminSchedule
          groups={groups.data ?? []}
          groupId={adminGroupId}
          schedule={adminSchedule.data}
          days={adminDays}
          slots={timeSlots.data ?? []}
          currentMinutes={currentMinutes}
          token={adminSession.token}
          onGroupChange={setAdminGroupId}
          onWeekMove={moveAdminWeek}
          onUnauthorized={logoutAdmin}
        />
      )}
    </main>

    <BottomNav view={view} onNavigate={nav} />
  </div>
}
