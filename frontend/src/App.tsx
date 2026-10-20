import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, FileSpreadsheet, Upload, X } from 'lucide-react'
import { BottomNav, DaySchedule, Header, WeekGrid } from './ScheduleComponents'
import { demoWeek as week, parseSchedules } from './scheduleData'
import type { Day, View } from './types'

export function App() {
  // Текущий экран и выбор расписания.
  const [view, setView] = useState<View>('day')
  const [scheduleMode, setScheduleMode] = useState<'day' | 'week'>('day')
  const [selectedDay, setSelectedDay] = useState(0)
  const [weekOffset, setWeekOffset] = useState(0)

  // Данные группы и выбранного занятия для изменения.
  const [changeDayIndex, setChangeDayIndex] = useState(2)
  const [changeLessonIndex, setChangeLessonIndex] = useState(0)
  const [direction, setDirection] = useState<'ПИ' | 'ПрИ'>('ПИ')
  const [group, setGroup] = useState('ПИ-201')
  const [course, setCourse] = useState('2 курс')
  const [changeType, setChangeType] = useState<'Перенос' | 'Отмена' | 'Замена'>('Перенос')

  // Импорт, публикация и взаимодействие с календарём.
  const [fileName, setFileName] = useState('')
  const [parsedSchedules, setParsedSchedules] = useState<Record<string, Day[]> | null>(null)
  const [parsedGroups, setParsedGroups] = useState<string[]>([])
  const [now, setNow] = useState(() => new Date())
  const [slideDirection, setSlideDirection] = useState<'next' | 'prev'>('next')
  const [dragX, setDragX] = useState(0)
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef<{ x: number; y: number } | null>(null)
  const ignoreDateClick = useRef(false)
  const [uploadError, setUploadError] = useState('')
  const [published, setPublished] = useState(false)
  const [confirmPublish, setConfirmPublish] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000)
    return () => window.clearInterval(timer)
  }, [])

  // Вычисляемые данные для экранов расписания и администрирования.
  const currentDay = week[selectedDay] ?? week[0]
  const displayedWeek = weekOffset + 2
  const parity = displayedWeek % 2 === 0 ? 2 : 1
  const weekStart = new Date(2026, 9, 19 + weekOffset * 7)
  const uploadedWeek = parsedSchedules?.[group] ?? null
  const groupOptions = parsedGroups.length
    ? parsedGroups.filter((name) => name.startsWith(`${direction}-${course[0]}`))
    : [1, 2, 3, 4].map((number) => `${direction}-${course[0]}0${number}`)
  const shownDays = (uploadedWeek ?? week).map((day, index) => ({
    ...day,
    date: new Date(
      weekStart.getFullYear(),
      weekStart.getMonth(),
      weekStart.getDate() + index,
    ).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }),
    lessons: day.lessons.filter((lesson) => lesson.parity === undefined || lesson.parity === parity),
  }))
  const todayIndex = shownDays.findIndex((_, index) => {
    const date = new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate() + index)
    return date.getFullYear() === now.getFullYear()
      && date.getMonth() === now.getMonth()
      && date.getDate() === now.getDate()
  })
  const currentMinutes = now.getHours() * 60 + now.getMinutes()
  const changeLessons = shownDays[changeDayIndex]?.lessons ?? []
  const changeLesson = changeLessons[changeLessonIndex] ?? changeLessons[0] ?? week[2].lessons[0]

  // Обработчики переходов и жестов календаря.
  const moveWeek = (delta: number) => {
    setSlideDirection(delta > 0 ? 'next' : 'prev')
    setWeekOffset((value) => value + delta)
  }

  const handleWeekDragStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    dragStart.current = { x: event.clientX, y: event.clientY }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handleWeekDragMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragStart.current) return

    const dx = event.clientX - dragStart.current.x
    const dy = event.clientY - dragStart.current.y
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 8) {
      event.preventDefault()
      setDragging(true)
      setDragX(dx)
    }
  }

  const handleWeekDragEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
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

  const isAdmin = ['admin', 'change', 'preview', 'excel'].includes(view)
  const changePreview = changeLesson

  const nav = (next: View) => {
    setView(next)
    setMenuOpen(false)
    if (next === 'day') setScheduleMode('day')
    if (next === 'week') setScheduleMode('week')
  }

  return <div className="app-shell">
    <Header
      title={view === 'group' ? 'Выберите группу' : isAdmin ? ({ admin: 'Управление расписанием', change: 'Временное изменение', preview: 'Проверка изменений', excel: 'Работа с Excel' } as Record<string, string>)[view] : 'Расписание'}
      subtitle={isAdmin ? 'Администратор' : view === 'group' ? 'Настройте расписание для своей группы' : `Институт ИТ · ${group}`}
      onBack={view === 'change' || view === 'excel' || view === 'preview' ? () => nav(view === 'preview' ? 'change' : 'admin') : undefined}
      onMenu={() => setMenuOpen((open) => !open)}
    />
    {menuOpen && <div className="role-switch-menu"><span>ДЕМО-РЕЖИМ</span><button onClick={() => nav('day')}>Студенческое расписание</button><button onClick={() => nav('admin')}>Администрирование расписания</button></div>}

    <main className="content">
      {view === 'group' && <section className="screen-card selection-screen">
        <div className="eyebrow">ПЕРВЫЙ ШАГ</div><h1>Выберите свою группу</h1><p className="muted">Группа сохранится на этом устройстве.</p>
        <label className="field-label">Институт</label><button className="select-field">Институт информационных технологий <ChevronDown size={17} /></button>
        <label className="field-label">Курс</label><div className="choice-row">{['1 курс', '2 курс', '3 курс', '4 курс'].map((item) => <button key={item} className={`choice ${course === item ? 'selected' : ''}`} onClick={() => { setCourse(item); setGroup(`${direction}-${item[0]}01`) }}>{item.split(' ')[0]}</button>)}</div>
        <label className="field-label">Направление</label><div className="choice-row"><button className={`choice ${direction === 'ПИ' ? 'selected' : ''}`} onClick={() => { setDirection('ПИ'); setGroup(`ПИ-${course[0]}01`) }}>ПИ</button><button className={`choice ${direction === 'ПрИ' ? 'selected' : ''}`} onClick={() => { setDirection('ПрИ'); setGroup(`ПрИ-${course[0]}01`) }}>ПрИ</button></div>
        <label className="field-label">Группа</label><div className="group-grid">{groupOptions.map((item) => <button key={item} className={`group-option ${group === item ? 'selected' : ''}`} onClick={() => setGroup(item)}>{item}</button>)}</div>
        <button className="button button-primary full" onClick={() => nav('day')}>Показать расписание <ChevronRight size={17} /></button>
      </section>}

      {(view === 'day' || view === 'week') && <>
        <section className="schedule-intro">
          <div className="week-line"><div><span className="eyebrow">{shownDays[0]?.date} — {shownDays[shownDays.length - 1]?.date}</span><h1>Неделя {displayedWeek} <span className="parity">{parity === 1 ? 'нечётная' : 'чётная'}</span></h1></div><button className="icon-button outlined" aria-label="Предыдущая неделя" onClick={() => moveWeek(-1)}><ChevronLeft size={18} /></button><button className="icon-button outlined" aria-label="Следующая неделя" onClick={() => moveWeek(1)}><ChevronRight size={18} /></button></div>
          <div className="segmented"><button className={scheduleMode === 'day' ? 'active' : ''} onClick={() => { setScheduleMode('day'); setView('day') }}>На день</button><button className={scheduleMode === 'week' ? 'active' : ''} onClick={() => { setScheduleMode('week'); setView('week') }}>На неделю</button></div>
        </section>
        {scheduleMode === 'week' ? <WeekGrid days={shownDays} todayIndex={todayIndex} currentMinutes={currentMinutes} /> : <>
          <div className="week-picker-clip"><div key={weekOffset} className={`date-strip week-picker ${dragging ? 'dragging' : `slide-${slideDirection}`}`} style={dragging ? { transform: `translateX(${dragX}px)` } : undefined} onPointerDown={handleWeekDragStart} onPointerMove={handleWeekDragMove} onPointerUp={handleWeekDragEnd} onPointerCancel={handleWeekDragEnd}>{shownDays.map((day, index) => <button className={`date-cell ${selectedDay === index ? 'active' : ''}`} key={day.date} onClick={() => { if (ignoreDateClick.current) return; setSelectedDay(index) }}><span>{['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'][index]}</span><strong>{day.date.split(' ')[0]}</strong></button>)}</div></div>
          <DaySchedule day={shownDays[selectedDay] ?? currentDay} />
        </>}
      </>}

      {view === 'admin' && <section className="admin-home">
        <div className="welcome"><div className="eyebrow">РАСПИСАНИЕ ЧЕЛГУ</div><h1>Что нужно сделать?</h1><p className="muted">Выберите курс и группу, чтобы начать.</p></div>
        <label className="field-label">Курс</label><select className="select-field" value={course} onChange={e => { setCourse(e.target.value); const next = parsedGroups.find(name => name.startsWith(`${direction}-${e.target.value[0]}`)); setGroup(next ?? `${direction}-${e.target.value[0]}01`) }}>{['1 курс', '2 курс', '3 курс', '4 курс'].map(value => <option key={value}>{value}</option>)}</select>
        <label className="field-label">Направление</label><select className="select-field" value={direction} onChange={e => { const nextDirection = e.target.value as 'ПИ' | 'ПрИ'; setDirection(nextDirection); setGroup(parsedGroups.find(name => name.startsWith(`${nextDirection}-${course[0]}`)) ?? `${nextDirection}-${course[0]}01`) }}><option>ПИ</option><option>ПрИ</option></select>
        <label className="field-label">Группа</label><select className="select-field" value={groupOptions.includes(group) ? group : groupOptions[0] ?? group} onChange={e => setGroup(e.target.value)}>{groupOptions.map(name => <option key={name}>{name}</option>)}</select>
        <button className="button button-primary full" onClick={() => nav('excel')}><Upload size={17} />Загрузить расписание</button>
        <button className="button button-secondary full" onClick={() => nav('change')}>Внести временное изменение</button>
        <button className="quiet-link" onClick={() => nav('excel')}>Скачать Excel всех групп курса <ChevronRight size={15} /></button>
        <div className="admin-status"><span className="status-dot" />Расписание опубликовано <span>Обновлено 18 октября</span></div>
      </section>}

      {view === 'change' && <section className="form-screen">
        <div className="stepper"><span className="step active">1</span><i /><span className="step">2</span></div>
        <div className="screen-heading"><span className="eyebrow">ШАГ 1 ИЗ 2</span><h1>Укажите изменение</h1><p className="muted">Сначала выберите занятие, затем проверьте результат.</p></div>
        <label className="field-label">Группа</label><select className="select-field" value={groupOptions.includes(group) ? group : groupOptions[0] ?? group} onChange={e => setGroup(e.target.value)}>{groupOptions.map(name => <option key={name}>{name}</option>)}</select>
        <label className="field-label">Дата занятия</label><select className="select-field" value={changeDayIndex} onChange={e => { setChangeDayIndex(Number(e.target.value)); setChangeLessonIndex(0) }}>{shownDays.map((day, i) => <option key={i} value={i}>{day.date}</option>)}</select>
        <label className="field-label">Занятие</label><select className="select-field lesson-select" value={changeLessonIndex} onChange={e => setChangeLessonIndex(Number(e.target.value))}>{changeLessons.length ? changeLessons.map((lesson, i) => <option key={i} value={i}>{`${lesson.time} · ${lesson.subject}`}</option>) : <option value={0}>На этот день занятий нет</option>}</select>
        <label className="field-label">Что изменится?</label><div className="choice-row change-types">{(['Перенос', 'Отмена', 'Замена'] as const).map((item) => <button className={`choice ${changeType === item ? 'selected' : ''}`} key={item} onClick={() => setChangeType(item)}>{item}</button>)}</div>
        {changeType !== 'Отмена' && <><label className="field-label">Новое время</label><div className="two-fields"><button className="select-field">13:00 <ChevronDown size={14} /></button><button className="select-field">14:30 <ChevronDown size={14} /></button></div><label className="field-label">Аудитория</label><input className="text-field" defaultValue="Главный корпус · 204" /></>}
        <label className="field-label">Изменение действует до</label><button className="select-field">30 октября 2026 <CalendarDays size={17} /></button>
        <button className="button button-primary full" onClick={() => nav('preview')}>Проверить результат <ChevronRight size={17} /></button>
      </section>}

      {view === 'preview' && <section className="form-screen preview-screen">
        <div className="stepper"><span className="step done"><Check size={14} /></span><i /><span className="step active">2</span></div>
        <div className="screen-heading"><span className="eyebrow">ПЕРЕД ПУБЛИКАЦИЕЙ</span><h1>Проверьте изменение</h1><p className="muted">Убедитесь, что время и аудитория указаны верно.</p></div>
        <div className="preview-info"><span className="eyebrow">ЗАТРОНУТАЯ ГРУППА</span><strong>{group} · {shownDays[changeDayIndex]?.date}</strong><span>Действует до 30 октября 2026</span></div>
        <div className="compare-card"><div className="compare-label">БЫЛО</div><div className="compare-row old"><strong>{changePreview.previousTime ?? '12:00–13:30'}</strong><div><b>{changePreview.subject}</b><span>Ауд. 204</span></div></div><div className="compare-label next">СТАНЕТ</div><div className="compare-row new"><strong>{changePreview.time}</strong><div><b>{changePreview.subject}</b><span>Главный корпус · 204</span></div><span className="badge badge-changed">Изменено</span></div></div>
        {published && <div className="success-note"><Check size={17} />Изменение опубликовано</div>}
        <button className="button button-secondary full" onClick={() => nav('change')}>Вернуться к редактированию</button>
        <button className="button button-primary full" onClick={() => setConfirmPublish(true)}>Опубликовать</button>
      </section>}

      {view === 'excel' && <section className="form-screen excel-screen">
        <div className="screen-heading"><span className="eyebrow">ТАБЛИЦЫ РАСПИСАНИЯ</span><h1>Загрузка и выгрузка</h1><p className="muted">Работа с расписанием выбранного курса.</p></div>
        <label className="field-label">Курс</label><select className="select-field" value={course} onChange={e => { setCourse(e.target.value); const next = parsedGroups.find(name => name.startsWith(`${direction}-${e.target.value[0]}`)); setGroup(next ?? `${direction}-${e.target.value[0]}01`) }}>{['1 курс', '2 курс', '3 курс', '4 курс'].map(value => <option key={value}>{value}</option>)}</select>
        <label className="field-label">Направление</label><select className="select-field" value={direction} onChange={e => { const nextDirection = e.target.value as 'ПИ' | 'ПрИ'; setDirection(nextDirection); setGroup(parsedGroups.find(name => name.startsWith(`${nextDirection}-${course[0]}`)) ?? `${nextDirection}-${course[0]}01`) }}><option>ПИ</option><option>ПрИ</option></select>
        <label className="field-label">Группа в файле</label><select className="select-field" value={groupOptions.includes(group) ? group : groupOptions[0] ?? group} onChange={e => setGroup(e.target.value)}>{groupOptions.map(name => <option key={name}>{name}</option>)}</select>
        <div className="upload-area"><div className="upload-icon"><FileSpreadsheet size={22} /></div><strong>{fileName || 'Загрузите Excel-файл'}</strong><span>{fileName ? 'Ищем группы во всех листах' : 'Формат .xlsx или .xls · расписание курса'}</span><label className="button button-secondary upload-button"><Upload size={16} />Выбрать файл<input type="file" accept=".xlsx,.xls" onChange={async (event) => { const file = event.target.files?.[0]; if (!file) return; setFileName(file.name); setUploadError(''); setParsedSchedules(null); try { const parsed = await parseSchedules(file); setParsedSchedules(parsed.schedules); setParsedGroups(parsed.groups); if (!parsed.schedules[group]) { const next = parsed.groups.find(name => name.startsWith(`${direction}-${course[0]}`)) ?? parsed.groups[0]; setGroup(next); setDirection(next.startsWith('ПИ-') ? 'ПИ' : 'ПрИ'); setCourse(`${next.split('-')[1][0]} курс`) } } catch (error) { setParsedSchedules(null); setParsedGroups([]); setUploadError(error instanceof Error ? error.message : 'Не удалось разобрать файл') } }} /></label></div>
        {uploadError && <div className="error-note">{uploadError}</div>}
        {uploadedWeek && <div className="success-note"><Check size={17} />Найдено {parsedGroups.length} групп во всех листах. {group}: {uploadedWeek.reduce((sum, day) => sum + day.lessons.length, 0)} занятий</div>}
        <button className="button button-primary full" disabled={!uploadedWeek} onClick={() => setPublished(true)}>{published ? <><Check size={17} />Файл загружен</> : 'Загрузить расписание'}</button>
        <div className="divider"><span>ВЫГРУЗКА</span></div><div className="export-row"><div className="upload-icon small"><FileSpreadsheet size={18} /></div><div><strong>Расписание курса</strong><span>Все группы в одном Excel-файле</span></div></div><button className="button button-secondary full" onClick={() => setPublished(true)}>{published ? 'Файл подготовлен' : 'Скачать расписание курса'}</button>
      </section>}
    </main>

    <BottomNav view={view} onNavigate={nav} />
    {confirmPublish && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setConfirmPublish(false) }}><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><button className="modal-close" aria-label="Закрыть" onClick={() => setConfirmPublish(false)}><X size={18} /></button><div className="modal-icon"><Check size={22} /></div><span className="eyebrow">ПУБЛИКАЦИЯ ИЗМЕНЕНИЯ</span><h2 id="confirm-title">Опубликовать изменение?</h2><p>Обновлённое расписание группы {group} станет доступно студентам.</p><button className="button button-primary full" onClick={() => { setPublished(true); setConfirmPublish(false) }}>Опубликовать</button><button className="quiet-link centered" onClick={() => setConfirmPublish(false)}>Вернуться к проверке</button></section></div>}
  </div>
}
