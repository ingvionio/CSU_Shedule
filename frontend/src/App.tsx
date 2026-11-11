import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type PointerEvent as ReactPointerEvent } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { clearAdminSession, readAdminSession, readSelectedGroup, writeAdminSession, writeSelectedGroup } from './api/cache'
import { useCurrentWeek, useGroups, useHomework, useInbox, usePersonalNotes, useSchedule, useTimeSlots } from './api/queries'
import { forgetMoodle, logoutStudent, useStudentSession } from './api/student'
import { BottomNav, DaySchedule, Header, PersonalNotePreview, WeekGrid, dayNumber, weekRangeLabel } from './ScheduleComponents'
import { AdminLogin } from './pages/admin/AdminLogin'
import { AdminFeedback } from './pages/admin/AdminFeedback'
import { AdminSchedule } from './pages/admin/AdminSchedule'
import { AdminMessages } from './pages/admin/AdminMessages'
import { AdminImports } from './pages/admin/AdminImports'
import { AdminHomeworkEditors } from './pages/admin/AdminHomeworkEditors'
import { useNavigation } from './navigation'
import { ContextHelp } from './ContextHelp'
import { Landing } from './pages/Landing'
import { Help } from './pages/Help'
import { CampusMap } from './pages/CampusMap'
import { MoodleLogin } from './pages/MoodleLogin'
import { StudentFeedback } from './pages/feedback/StudentFeedback'
import { StudentMessages } from './pages/messages/StudentMessages'
import { GroupHomeworkPanel } from './pages/homework/GroupHomeworkPanel'
import { PersonalNoteDialog } from './pages/homework/PersonalNoteDialog'
import type { GroupHomework, PersonalNote } from './api/types'
import type { AdminSession, Day, Group, Lesson, StudentSession, View } from './types'

const WEEKDAY_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
const COURSES = [1, 2, 3, 4]
const mobileCardsQuery = window.matchMedia('(max-width: 600px)')
const subscribeMobileCards = (notify: () => void) => {
  mobileCardsQuery.addEventListener('change', notify)
  return () => mobileCardsQuery.removeEventListener('change', notify)
}
const ADMIN_SUBTITLES = {
  schedule: 'Управление расписанием',
  messages: 'Сообщения студентам',
  feedback: 'Обращения студентов',
  homework: 'Редакторы групповой домашки',
  imports: 'Загрузка расписаний',
}

/**
 * Направление подготовки приходит с бэкенда. Разбор названия остался запасным
 * вариантом для списка групп, сохранённого до появления поля.
 */
function directionOf(group: Group): string {
  return group.direction ?? group.name.match(/(ПрИ|ПИ|БИ)/)?.[1] ?? group.name
}

/** `/?message=12` — ссылка из push-уведомления. */
function messageFromUrl(url: string): number | null {
  const value = Number(new URL(url, window.location.origin).searchParams.get('message'))
  return Number.isInteger(value) && value > 0 ? value : null
}

export function App() {
  const mobileCards = useSyncExternalStore(subscribeMobileCards, () => mobileCardsQuery.matches)
  const studentSession = useStudentSession()
  const [requestedMessage, setRequestedMessage] = useState(() => messageFromUrl(window.location.href))
  const [view, setView] = useNavigation(studentSession !== null)
  const [groupId, setGroupId] = useState<number | null>(() => studentSession ? studentSession.profile.group_id : readSelectedGroup())
  const [adminGroupId, setAdminGroupId] = useState<number | null>(null)
  const [weekNumber, setWeekNumber] = useState<number | null>(null)
  const [selectedDay, setSelectedDay] = useState(0)
  const [now, setNow] = useState(() => new Date())
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Меню ☰ закрывается нажатием в любом месте вне меню и клавишей Esc.
  // Кнопку ☰ не считаем «вне»: её нажатие и так переключает меню.
  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Element | null
      if (menuRef.current?.contains(target) || target?.closest('[aria-label="Меню"]')) return
      setMenuOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])
  const [adminSession, setAdminSession] = useState<AdminSession | null>(() => readAdminSession())
  const [adminSection, setAdminSection] = useState<'schedule' | 'messages' | 'feedback' | 'homework' | 'imports'>('schedule')

  // Выбор группы на экране настройки.
  const [course, setCourse] = useState(1)
  const [direction, setDirection] = useState('ПИ')

  // Жесты и анимация переключения недель.
  const [slideDirection, setSlideDirection] = useState<'next' | 'prev'>('next')
  const [dragX, setDragX] = useState(0)
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef<{ x: number; y: number } | null>(null)
  const ignoreDateClick = useRef(false)
  const mapReturnView = useRef<View>('day')

  const groups = useGroups()
  const timeSlots = useTimeSlots()
  const currentWeek = useCurrentWeek()
  const schedule = useSchedule(groupId, weekNumber)
  const adminSchedule = useSchedule(adminGroupId, weekNumber)

  const homework = useHomework(
    studentSession !== null && groupId !== null && studentSession.profile.group_id === groupId,
    schedule.data?.week.start_date,
    schedule.data?.week.end_date,
  )
  const homeworkByLesson = new Map<string, GroupHomework[]>()
  if (studentSession?.profile.group_id === groupId) {
    for (const item of homework.data?.items ?? []) {
      if (item.group_id !== groupId || item.lesson_id === null || item.lesson_date === null || item.status === 'archived') continue
      const key = `${item.lesson_date}:l-${item.lesson_id}`
      homeworkByLesson.set(key, [...(homeworkByLesson.get(key) ?? []), item])
    }
  }
  const homeworkCounts = new Map([...homeworkByLesson].map(([key, items]) => [key, items.length]))
  const personalNotes = usePersonalNotes()
  const [noteSelection, setNoteSelection] = useState<{ groupId: number; day: Day; lesson: Lesson; note?: PersonalNote } | null>(null)
  const notesByKey = new Map((personalNotes.data ?? []).map((note) => [note.occurrence_key, note]))
  const openNote = (lesson: Lesson, day: Day) => {
    if (groupId !== null && studentSession && personalNotes.isSuccess && lesson.note_key) {
      setNoteSelection({ groupId, lesson, day, note: notesByKey.get(lesson.note_key) })
    }
  }

  const inbox = useInbox(studentSession !== null)
  const queryClient = useQueryClient()

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000)
    return () => window.clearInterval(timer)
  }, [])

  // При наличии сессии студента восстанавливаем его группу
  useEffect(() => {
    if (studentSession && groupId !== studentSession.profile.group_id) {
      setGroupId(studentSession.profile.group_id)
      if (studentSession.profile.group_id !== null) writeSelectedGroup(studentSession.profile.group_id)
    }
  }, [studentSession, groupId])

  useEffect(() => {
    if (studentSession && view === 'login') setView(requestedMessage !== null ? 'messages' : 'day', true)
  }, [studentSession, view, requestedMessage, setView])

  useEffect(() => {
    const restoreMessage = () => {
      const id = messageFromUrl(window.location.href)
      if (id !== null) setRequestedMessage(id)
    }
    window.addEventListener('popstate', restoreMessage)
    return () => window.removeEventListener('popstate', restoreMessage)
  }, [])

  // Service worker сообщает о новом push и о нажатии на уведомление в уже открытом приложении.
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return
    const handle = (event: MessageEvent) => {
      if (event.data?.type === 'messages-updated') queryClient.invalidateQueries({ queryKey: ['inbox'] })
      if (event.data?.type === 'open-message') {
        queryClient.invalidateQueries({ queryKey: ['inbox'] })
        setRequestedMessage(messageFromUrl(event.data.url))
        setView('messages')
      }
    }
    navigator.serviceWorker.addEventListener('message', handle)
    return () => navigator.serviceWorker.removeEventListener('message', handle)
  }, [queryClient])

  // По умолчанию открывается текущая неделя.
  useEffect(() => {
    if (weekNumber === null && currentWeek.data) setWeekNumber(currentWeek.data.number)
  }, [currentWeek.data, weekNumber])

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

  const handleMoodleLogin = (session: StudentSession) => {
    setGroupId(session.profile.group_id)
    if (session.profile.group_id) {
      setGroupId(session.profile.group_id)
      writeSelectedGroup(session.profile.group_id)
      const matchedGroup = (groups.data ?? []).find((g) => g.id === session.profile.group_id)
      if (matchedGroup) {
        setCourse(matchedGroup.course)
        setDirection(directionOf(matchedGroup))
      }
    }
    setWeekNumber(currentWeek.data?.number ?? null)
    setView(requestedMessage !== null ? 'messages' : (view === 'login' || view === 'landing' ? 'day' : view), true)
    queryClient.invalidateQueries({ queryKey: ['inbox'] })
  }

  const handleStudentLogout = () => {
    logoutStudent()
    setGroupId(null)
    setRequestedMessage(null)
    setView('landing', true)
    setMenuOpen(false)
  }

  const handleForgetMoodle = async () => {
    await forgetMoodle()
    setGroupId(null)
    setRequestedMessage(null)
    setView('landing', true)
    setMenuOpen(false)
  }

  // На текущей неделе открываем сегодняшний день.
  useEffect(() => {
    const todayIndex = days.findIndex((day) => day.is_today)
    if (todayIndex >= 0) setSelectedDay(todayIndex)
  }, [week?.number, days.length])

  const groupOptions = useMemo(
    () => (groups.data ?? []).filter((group) => group.course === course && directionOf(group) === direction),
    [groups.data, course, direction],
  )

  const directions = useMemo(() => {
    const available = (groups.data ?? []).filter((group) => group.course === course)
    return [...new Set(available.map(directionOf))]
  }, [groups.data, course])

  const selectedGroup: Group | undefined = (groups.data ?? []).find((group) => group.id === groupId)
  const currentMinutes = now.getHours() * 60 + now.getMinutes()

  const chooseGroup = (group: Group) => {
    if (studentSession) {
      // Группу авторизованного студента менять нельзя — она строго зафиксирована из Moodle
      return
    }
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
      setDragging(true)
      const clamped = Math.sign(dx) * Math.min(Math.abs(dx), 140)
      setDragX(clamped)
    }
  }

  const handleDragEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragStart.current) return
    const dx = event.clientX - dragStart.current.x
    const dy = event.clientY - dragStart.current.y
    const wasDragging = dragging || Math.abs(dx) > 8
    dragStart.current = null
    setDragging(false)
    setDragX(0)

    if (wasDragging) {
      ignoreDateClick.current = true
      window.setTimeout(() => (ignoreDateClick.current = false), 80)
    }

    if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy)) {
      if (dx < 0 && week?.next != null) moveWeek(1)
      else if (dx > 0 && week?.prev != null) moveWeek(-1)
    }
  }

  const moveAdminWeek = (delta: number) => {
    const target = delta > 0 ? adminSchedule.data?.week.next : adminSchedule.data?.week.prev
    if (target != null) setWeekNumber(target)
  }

  const nav = (next: View) => {
    if (next === 'map') mapReturnView.current = view === 'map' ? 'day' : view
    setView(next)
    setMenuOpen(false)
  }

  const publicView = view === 'landing' || view === 'help' || view === 'feedback'
  const needsLogin = !studentSession && view !== 'admin' && !publicView

  return (
    <>
      <CampusMap active={view === 'map' && !needsLogin} onBack={() => nav(mapReturnView.current)} />
      <div className={`app-shell ${view === 'landing' ? 'landing-shell' : ''}`} hidden={view === 'map' && !needsLogin}>
        <Header
          title={
            view === 'landing' ? 'Расписание ИИТ' : view === 'help' ? 'Помощь' : view === 'group'
              ? studentSession
                ? 'Профиль студента'
                : 'Выберите группу'
              : view === 'admin'
                ? 'Администрирование'
                : view === 'feedback'
                  ? 'Вопросы'
                  : view === 'messages'
                    ? 'Сообщения'
                    : !studentSession
                      ? 'Авторизация'
                      : 'Расписание'
          }
          subtitle={
            view === 'landing' || view === 'help' ? 'Институт информационных технологий · ЧелГУ' : view === 'group'
              ? studentSession
                ? 'Данные авторизации Moodle'
                : 'Группа сохранится на этом устройстве'
              : view === 'admin'
                ? ADMIN_SUBTITLES[adminSection]
                : needsLogin
                  ? 'Институт ИТ ЧелГУ · Вход через Moodle'
                  : `Институт ИТ · ${selectedGroup?.name ?? studentSession?.profile.group_name ?? 'ЧелГУ'}`
          }
          onBack={view === 'help' || view === 'login' || (view === 'group' && groupId !== null) ? () => nav(studentSession ? 'day' : 'landing') : undefined}
          onMenu={() => setMenuOpen((open) => !open)}
        />
        {menuOpen && (
          <div className="role-switch-menu" ref={menuRef}>
            <span>МЕНЮ</span>
            {studentSession && (
              <div style={{ padding: '6px 12px', fontSize: '12px', color: '#666', borderBottom: '1px solid #eee' }}>
                <div style={{ fontWeight: 600, color: '#212529' }}>{studentSession.profile.full_name}</div>
                <div>Группа: {studentSession.profile.group_name ?? 'не определена'}</div>
              </div>
            )}
            {studentSession && <button onClick={() => nav('day')}>Студенческое расписание</button>}
            <button onClick={() => nav('landing')}>О проекте</button>
            <button onClick={() => nav('help')}>Помощь</button>
            <button onClick={() => nav('admin')}>Администрирование расписания</button>
            {studentSession && <button onClick={handleStudentLogout}>Выйти из аккаунта</button>}
            {studentSession && (
              <button onClick={handleForgetMoodle} style={{ color: '#c92a2a' }}>
                Сбросить пароль Moodle
              </button>
            )}
            {adminSession && <button onClick={logoutAdmin}>Выйти из админки</button>}
          </div>
        )}

        <main className="content">
          {view === 'landing' ? <Landing authenticated={Boolean(studentSession)} onStart={() => nav(studentSession ? 'day' : 'login')} onHelp={() => nav('help')} onAdmin={() => nav('admin')} />
          : view === 'help' ? <Help onFeedback={() => nav('feedback')} />
          : needsLogin ? (
            <MoodleLogin onLogin={handleMoodleLogin} onGoToAdmin={() => nav('admin')} />
          ) : (
            <>
              {(view === 'day' || view === 'week' || view === 'admin') && groups.isLoading && !groups.data && <div className="state-note">Загружаем расписание…</div>}
              {(view === 'day' || view === 'week' || view === 'admin') && groups.isError && !groups.data && (
                <div className="state-note error-note">
                  <span>{(groups.error as Error).message}</span>
                  <button className="button button-secondary" onClick={() => groups.refetch()}>
                    <RefreshCw size={16} />Повторить
                  </button>
                </div>
              )}

              {view === 'group' && (
                studentSession ? (
                  <section className="screen-card selection-screen">
                    <div className="eyebrow">МОЙ ПРОФИЛЬ</div>
                    <h1>Профиль студента</h1>
                    <p className="muted">Данные синхронизированы с платформой Moodle ЧелГУ.</p>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', marginTop: '1.25rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color, #e9ecef)', paddingBottom: '0.6rem' }}>
                        <span className="field-label" style={{ margin: 0 }}>ФИО</span>
                        <strong>{studentSession.profile.full_name}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color, #e9ecef)', paddingBottom: '0.6rem' }}>
                        <span className="field-label" style={{ margin: 0 }}>Логин Moodle</span>
                        <span>@{studentSession.profile.moodle_username}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color, #e9ecef)', paddingBottom: '0.6rem' }}>
                        <span className="field-label" style={{ margin: 0 }}>Академическая группа</span>
                        <strong style={{ color: 'var(--primary, #1971c2)' }}>
                          {selectedGroup?.name ?? studentSession.profile.group_name ?? '—'}
                        </strong>
                      </div>
                    </div>

                    <div className="state-note" style={{ marginTop: '1.25rem', textAlign: 'left', fontSize: '0.85rem' }}>
                      Группа определена автоматически через Moodle (eu.iit.csu.ru) по курсам текущего семестра и не может быть изменена вручную.
                    </div>

                    <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.75rem' }}>
                      <button className="button button-primary" style={{ flex: 1 }} onClick={() => nav('day')}>
                        К расписанию
                      </button>
                      <button className="button button-secondary" onClick={handleForgetMoodle}>
                        Выйти из Moodle
                      </button>
                    </div>
                  </section>
                ) : (
                  <section className="screen-card selection-screen">
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
                        >
                          {item}
                        </button>
                      ))}
                    </div>

                    <label className="field-label">Направление</label>
                    <div className="choice-row">
                      {directions.map((item) => (
                        <button
                          key={item}
                          className={`choice ${direction === item ? 'selected' : ''}`}
                          onClick={() => setDirection(item)}
                        >
                          {item}
                        </button>
                      ))}
                    </div>

                    <label className="field-label">Группа</label>
                    {groupOptions.length ? (
                      <div className="group-grid">
                        {groupOptions.map((group) => (
                          <button
                            key={group.id}
                            className={`group-option ${groupId === group.id ? 'selected' : ''}`}
                            onClick={() => chooseGroup(group)}
                          >
                            {group.name}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="empty-day">На этом направлении групп нет</div>
                    )}
                  </section>
                )
              )}

              {view === 'feedback' && <StudentFeedback groupId={groupId} />}

              {view === 'messages' && (
                <StudentMessages group={selectedGroup} onChooseGroup={() => nav('group')} requestedId={requestedMessage} />
              )}

              {groupId === null && (view === 'day' || view === 'week') && !groups.isLoading && !groups.isError && (
                <div className="state-note">Ваша группа определяется через Moodle…</div>
              )}

              {groupId !== null && (view === 'day' || view === 'week') && (
                <>
                  <section className="schedule-intro">
                    <div className="week-line">
                      <div>
                        <span className="eyebrow">{week ? weekRangeLabel(week.start_date, week.end_date) : ' '}</span>
                        <h1>
                          Неделя {week?.number ?? '—'}{' '}
                          <span className="parity">
                            {week?.parity === 'odd' ? 'нечётная' : week?.parity === 'even' ? 'чётная' : ''}
                          </span>
                        </h1>
                      </div>
                      <button
                        className="icon-button outlined"
                        aria-label="Предыдущая неделя"
                        disabled={week?.prev == null}
                        onClick={() => moveWeek(-1)}
                      >
                        <ChevronLeft size={18} />
                      </button>
                      <button
                        className="icon-button outlined"
                        aria-label="Следующая неделя"
                        disabled={week?.next == null}
                        onClick={() => moveWeek(1)}
                      >
                        <ChevronRight size={18} />
                      </button>
                    </div>
                    <div className="segmented">
                      <button className={view === 'day' ? 'active' : ''} onClick={() => setView('day')}>
                        На день
                      </button>
                      <button className={view === 'week' ? 'active' : ''} onClick={() => setView('week')}>
                        На неделю
                      </button>
                    </div>
                  </section>

                  <ContextHelp ids={['views', 'parity', 'changes']} label="Как читать расписание" />

                  {schedule.isError && (
                    <div className="state-note error-note">
                      <span>{(schedule.error as Error).message}</span>
                      <button className="button button-secondary" onClick={() => schedule.refetch()}>
                        <RefreshCw size={16} />Повторить
                      </button>
                    </div>
                  )}

                  {!schedule.data && schedule.isLoading && <div className="state-note">Загружаем неделю…</div>}

                  {schedule.data &&
                    (view === 'week' ? (
                      <WeekGrid days={days} slots={timeSlots.data ?? []} currentMinutes={currentMinutes} />
                    ) : (
                      <>
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
                                onClick={() => {
                                  if (!ignoreDateClick.current) setSelectedDay(index)
                                }}
                              >
                                <span>{WEEKDAY_SHORT[index]}</span>
                                <strong>{dayNumber(day.date)}</strong>
                              </button>
                            ))}
                          </div>
                        </div>
                        {days[selectedDay] && (
                          <DaySchedule
                            day={days[selectedDay]}
                            onLessonClick={mobileCards && studentSession && personalNotes.isSuccess ? openNote : undefined}
                            renderLessonExtras={
                              studentSession
                                ? (lesson, day) => (
                                    <>
                                      {homeworkCounts.has(`${day.date}:${lesson.id}`) && (
                                        <span className="lesson-homework-badge">
                                          Домашка · {homeworkCounts.get(`${day.date}:${lesson.id}`)}
                                        </span>
                                      )}
                                      {lesson.note_key && notesByKey.get(lesson.note_key) && (
                                        <PersonalNotePreview
                                          key={notesByKey.get(lesson.note_key)!.id}
                                          body={notesByKey.get(lesson.note_key)!.body}
                                          onOpen={mobileCards ? undefined : () => openNote(lesson, day)}
                                        />
                                      )}
                                      {!mobileCards && (
                                        <button
                                          className="button button-secondary personal-note-button"
                                          disabled={!personalNotes.isSuccess || !lesson.note_key}
                                          onClick={() => openNote(lesson, day)}
                                        >
                                          {lesson.note_key && notesByKey.has(lesson.note_key)
                                            ? 'Изменить мою заметку'
                                            : 'Моя заметка'}
                                        </button>
                                      )}
                                    </>
                                  )
                                : undefined
                            }
                          />
                        )}
                      </>
                    ))}

                  {schedule.data && schedule.isStale && !navigator.onLine && (
                    <div className="state-note muted">
                      Показано сохранённое расписание · обновлено{' '}
                      {new Date(schedule.data.generated_at).toLocaleString('ru-RU', {
                        day: 'numeric',
                        month: 'long',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </div>
                  )}

                  {schedule.data && studentSession && (
                    <GroupHomeworkPanel
                      groupId={groupId}
                      weekStart={schedule.data.week.start_date}
                      weekEnd={schedule.data.week.end_date}
                      days={days}
                      selectedDay={selectedDay}
                    />
                  )}

                  {personalNotes.isError && studentSession && (
                    <div className="state-note error-note">
                      <span>Не удалось загрузить личные заметки: {personalNotes.error.message}</span>
                      <button className="button button-secondary" onClick={() => personalNotes.refetch()}>
                        Повторить
                      </button>
                    </div>
                  )}
                </>
              )}

              {view === 'admin' && !adminSession && <AdminLogin onLogin={loginAdmin} />}

              {view === 'admin' && adminSession && (
                <div className="admin-target-tabs admin-sections" aria-label="Раздел админки">
                  <button
                    className={adminSection === 'schedule' ? 'active' : ''}
                    onClick={() => setAdminSection('schedule')}
                  >
                    Расписание
                  </button>
                  <button
                    className={adminSection === 'imports' ? 'active' : ''}
                    onClick={() => setAdminSection('imports')}
                  >
                    Загрузка
                  </button>
                  <button
                    className={adminSection === 'messages' ? 'active' : ''}
                    onClick={() => setAdminSection('messages')}
                  >
                    Сообщения
                  </button>
                  <button
                    className={adminSection === 'feedback' ? 'active' : ''}
                    onClick={() => setAdminSection('feedback')}
                  >
                    Обращения
                  </button>
                  <button
                    className={adminSection === 'homework' ? 'active' : ''}
                    onClick={() => setAdminSection('homework')}
                  >
                    Домашка
                  </button>
                </div>
              )}

              {view === 'admin' && adminSession && adminSection === 'imports' && (
                <AdminImports token={adminSession.token} onUnauthorized={logoutAdmin} />
              )}

              {view === 'admin' && adminSession && adminSection === 'messages' && (
                <AdminMessages token={adminSession.token} groups={groups.data ?? []} onUnauthorized={logoutAdmin} />
              )}

              {view === 'admin' && adminSession && adminSection === 'feedback' && (
                <AdminFeedback token={adminSession.token} onUnauthorized={logoutAdmin} />
              )}

              {view === 'admin' && adminSession && adminSection === 'homework' && (
                <AdminHomeworkEditors
                  token={adminSession.token}
                  groups={groups.data ?? []}
                  groupId={adminGroupId}
                  onGroupChange={setAdminGroupId}
                />
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
            </>
          )}
        </main>

        {studentSession && view !== 'admin' && view !== 'landing' && (
          <BottomNav view={view} onNavigate={nav} unread={inbox.data?.unread_count ?? 0} hasSession={Boolean(studentSession)} />
        )}
        {noteSelection && studentSession && (
          <PersonalNoteDialog
            {...noteSelection}
            homework={homeworkByLesson.get(`${noteSelection.day.date}:${noteSelection.lesson.id}`) ?? []}
            homeworkLoading={homework.isPending}
            homeworkError={homework.isError ? homework.error.message : undefined}
            onRetryHomework={() => homework.refetch()}
            onClose={() => setNoteSelection(null)}
          />
        )}
      </div>
    </>
  )
}
