/**
 * Разметка админских экранов из первого прототипа.
 *
 * Сохранена для следующего этапа (временные изменения + загрузка Excel) и
 * НИГДЕ не подключена: маршрутов на неё нет. Данные здесь локальные, запросов
 * к API компонент не делает — загрузка Excel и публикация появятся,
 * когда на бэкенде будут админские эндпоинты.
 */

import { useState } from 'react'
import { CalendarDays, Check, ChevronDown, ChevronRight, FileSpreadsheet, Upload, X } from 'lucide-react'

type AdminView = 'admin' | 'change' | 'preview' | 'excel'

const COURSES = ['1 курс', '2 курс', '3 курс', '4 курс']

export function DemoAdminScreens() {
  const [view, setView] = useState<AdminView>('admin')
  const [course, setCourse] = useState('2 курс')
  const [direction, setDirection] = useState<'ПИ' | 'ПрИ'>('ПИ')
  const [group, setGroup] = useState('ПИ-201')
  const [changeType, setChangeType] = useState<'Перенос' | 'Отмена' | 'Замена'>('Перенос')
  const [confirmPublish, setConfirmPublish] = useState(false)
  const [published, setPublished] = useState(false)

  const groupOptions = [1, 2, 3, 4].map((number) => `${direction}-${course[0]}0${number}`)

  return <>
    {view === 'admin' && <section className="admin-home">
      <div className="welcome">
        <div className="eyebrow">РАСПИСАНИЕ ЧЕЛГУ</div>
        <h1>Что нужно сделать?</h1>
        <p className="muted">Выберите курс и группу, чтобы начать.</p>
      </div>
      <label className="field-label">Курс</label>
      <select className="select-field" value={course} onChange={(event) => setCourse(event.target.value)}>
        {COURSES.map((value) => <option key={value}>{value}</option>)}
      </select>
      <label className="field-label">Направление</label>
      <select
        className="select-field"
        value={direction}
        onChange={(event) => setDirection(event.target.value as 'ПИ' | 'ПрИ')}
      ><option>ПИ</option><option>ПрИ</option></select>
      <label className="field-label">Группа</label>
      <select className="select-field" value={group} onChange={(event) => setGroup(event.target.value)}>
        {groupOptions.map((name) => <option key={name}>{name}</option>)}
      </select>
      <button className="button button-primary full" onClick={() => setView('excel')}>
        <Upload size={17} />Загрузить расписание
      </button>
      <button className="button button-secondary full" onClick={() => setView('change')}>
        Внести временное изменение
      </button>
      <div className="admin-status">
        <span className="status-dot" />Расписание опубликовано <span>Обновлено 18 октября</span>
      </div>
    </section>}

    {view === 'change' && <section className="form-screen">
      <div className="stepper"><span className="step active">1</span><i /><span className="step">2</span></div>
      <div className="screen-heading">
        <span className="eyebrow">ШАГ 1 ИЗ 2</span>
        <h1>Укажите изменение</h1>
        <p className="muted">Сначала выберите занятие, затем проверьте результат.</p>
      </div>
      <label className="field-label">Группа</label>
      <select className="select-field" value={group} onChange={(event) => setGroup(event.target.value)}>
        {groupOptions.map((name) => <option key={name}>{name}</option>)}
      </select>
      <label className="field-label">Что изменится?</label>
      <div className="choice-row change-types">
        {(['Перенос', 'Отмена', 'Замена'] as const).map((item) => (
          <button
            className={`choice ${changeType === item ? 'selected' : ''}`}
            key={item}
            onClick={() => setChangeType(item)}
          >{item}</button>
        ))}
      </div>
      {changeType !== 'Отмена' && <>
        <label className="field-label">Новое время</label>
        <div className="two-fields">
          <button className="select-field">13:00 <ChevronDown size={14} /></button>
          <button className="select-field">14:30 <ChevronDown size={14} /></button>
        </div>
        <label className="field-label">Аудитория</label>
        <input className="text-field" defaultValue="204" />
      </>}
      <label className="field-label">Изменение действует до</label>
      <button className="select-field">30 октября 2026 <CalendarDays size={17} /></button>
      <button className="button button-primary full" onClick={() => setView('preview')}>
        Проверить результат <ChevronRight size={17} />
      </button>
    </section>}

    {view === 'preview' && <section className="form-screen preview-screen">
      <div className="stepper">
        <span className="step done"><Check size={14} /></span><i /><span className="step active">2</span>
      </div>
      <div className="screen-heading">
        <span className="eyebrow">ПЕРЕД ПУБЛИКАЦИЕЙ</span>
        <h1>Проверьте изменение</h1>
        <p className="muted">Убедитесь, что время и аудитория указаны верно.</p>
      </div>
      <div className="compare-card">
        <div className="compare-label">БЫЛО</div>
        <div className="compare-row old"><strong>12:00–13:30</strong><div><b>Занятие</b><span>Ауд. 204</span></div></div>
        <div className="compare-label next">СТАНЕТ</div>
        <div className="compare-row new">
          <strong>13:00–14:30</strong><div><b>Занятие</b><span>Ауд. 204</span></div>
          <span className="badge badge-changed">Изменено</span>
        </div>
      </div>
      {published && <div className="success-note"><Check size={17} />Изменение опубликовано</div>}
      <button className="button button-secondary full" onClick={() => setView('change')}>
        Вернуться к редактированию
      </button>
      <button className="button button-primary full" onClick={() => setConfirmPublish(true)}>Опубликовать</button>
    </section>}

    {view === 'excel' && <section className="form-screen excel-screen">
      <div className="screen-heading">
        <span className="eyebrow">ТАБЛИЦЫ РАСПИСАНИЯ</span>
        <h1>Загрузка и выгрузка</h1>
        <p className="muted">Работа с расписанием выбранного курса.</p>
      </div>
      <div className="upload-area">
        <div className="upload-icon"><FileSpreadsheet size={22} /></div>
        <strong>Загрузите Excel-файл</strong>
        <span>Формат .xlsx или .xls · расписание курса</span>
        <label className="button button-secondary upload-button">
          <Upload size={16} />Выбрать файл
          <input type="file" accept=".xlsx,.xls" disabled />
        </label>
      </div>
      <div className="divider"><span>ВЫГРУЗКА</span></div>
      <div className="export-row">
        <div className="upload-icon small"><FileSpreadsheet size={18} /></div>
        <div><strong>Расписание курса</strong><span>Все группы в одном Excel-файле</span></div>
      </div>
      <button className="button button-secondary full" disabled>Скачать расписание курса</button>
    </section>}

    {confirmPublish && <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => { if (event.target === event.currentTarget) setConfirmPublish(false) }}
    >
      <section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <button className="modal-close" aria-label="Закрыть" onClick={() => setConfirmPublish(false)}>
          <X size={18} />
        </button>
        <div className="modal-icon"><Check size={22} /></div>
        <span className="eyebrow">ПУБЛИКАЦИЯ ИЗМЕНЕНИЯ</span>
        <h2 id="confirm-title">Опубликовать изменение?</h2>
        <p>Обновлённое расписание группы {group} станет доступно студентам.</p>
        <button
          className="button button-primary full"
          onClick={() => { setPublished(true); setConfirmPublish(false) }}
        >Опубликовать</button>
        <button className="quiet-link centered" onClick={() => setConfirmPublish(false)}>
          Вернуться к проверке
        </button>
      </section>
    </div>}
  </>
}
