import { ArrowRight, BellRing, CalendarDays, Check, ClipboardList, MapPin, MessageCircleQuestion, MessagesSquare, NotebookPen } from 'lucide-react'

const features = [
  [CalendarDays, 'Расписание', 'Пары на день и неделю, преподаватели, аудитории и изменения.'],
  [MapPin, 'Карта университета', 'Поиск аудиторий и маршрутов на карте ЧелГУ.'],
  [ClipboardList, 'Домашние задания', 'Общие задания группы и ваши отметки выполнения.'],
  [NotebookPen, 'Личные заметки', 'Ваши записи к конкретным занятиям, отдельно от домашки группы.'],
  [MessagesSquare, 'Сообщения', 'Важное от сотрудников и подтверждение ознакомления.'],
  [MessageCircleQuestion, 'Обращения', 'Вопросы методисту, деканату и разработчикам.'],
  [BellRing, 'Уведомления', 'О новых сообщениях — при поддержке устройства и настройке сервиса.'],
] as const

export function Landing({ authenticated, onStart, onHelp, onAdmin }: {
  authenticated: boolean; onStart: () => void; onHelp: () => void; onAdmin: () => void
}) {
  return <div className="landing">
    <section className="landing-hero" aria-labelledby="landing-title">
      <div className="landing-copy">
        <div className="landing-institute"><img src="/icons/iit-logo.png" alt="Институт информационных технологий" /></div><span className="landing-kicker"><span /> СТУДЕНТАМ ИИТ ЧЕЛГУ</span>
        <h1 id="landing-title">Всё для учёбы<br />в <em>одном месте.</em></h1>
        <p>Расписание ИИТ — ваш учебный день под рукой. От первой пары до последней заметки: меньше поисков, больше времени на главное.</p>
        <button className="button button-primary landing-cta" onClick={onStart}>{authenticated ? 'Открыть приложение' : 'Войти через Moodle'}<ArrowRight size={18} /></button>
        <span className="landing-caption"><Check size={14} /> Группа определится автоматически через Moodle</span>
      </div>
      <div className="landing-preview" aria-label="Иллюстрация возможностей приложения, не актуальное расписание">
        <div className="preview-top"><img src="/icons/iit-shield.png" alt="" /><span>Расписание ИИТ<small>Ваш день, по порядку</small></span><span className="preview-dot" /></div>
        <div className="preview-heading"><span>МЕНЬШЕ ХАОСА</span><strong>Больше ясности</strong></div>
        <div className="preview-days" aria-hidden="true">{['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ'].map((day, i) => <span className={i === 1 ? 'selected' : ''} key={day}>{day}<b>{14 + i}</b></span>)}</div>
        <div className="preview-lesson"><CalendarDays size={22} /><div><strong>Следующая пара</strong><small>Время · преподаватель · аудитория</small></div><span className="preview-tag">Всё рядом</span></div>
        <div className="preview-note"><NotebookPen size={18} /><span>Идея, которую важно не забыть<small>Личная заметка к занятию</small></span></div>
        <div className="preview-footer"><ClipboardList size={16} /> Домашка группы <Check size={16} /><span>Под контролем</span></div>
        <small className="preview-example">Пример интерфейса</small>
      </div>
    </section>
    <section className="landing-features" aria-labelledby="features-title"><span className="eyebrow">НА КАЖДЫЙ УЧЕБНЫЙ ДЕНЬ</span><h2 id="features-title">Знакомые задачи. Один сервис.</h2><div className="feature-grid">{features.map(([Icon, title, text], i) => <article className="feature-card" key={title}><span className={`feature-icon feature-tone-${i % 3}`}><Icon size={21} /></span><h3>{title}</h3><p>{text}</p></article>)}</div></section>
    <section className="landing-start" aria-labelledby="start-title"><div><span className="eyebrow">ВСЕГО ТРИ ШАГА</span><h2 id="start-title">Начать проще,<br />чем найти аудиторию</h2><button className="quiet-link" onClick={onHelp}>Помощь и ответы на вопросы <ArrowRight size={16} /></button></div><ol>{[['Войдите через Moodle', 'Используйте привычную учётную запись eu.iit.csu.ru.'], ['Проверьте свою группу', 'Она появится в профиле автоматически.'], ['Откройте расписание', 'Пары, задания и сообщения уже рядом.']].map(([title, text]) => <li key={title}><strong>{title}</strong><p>{text}</p></li>)}</ol></section>
    <footer className="landing-footer"><span>Расписание ИИТ · ЧелГУ<small>Знак ИИТ предоставлен для оформления приложения.</small></span><button className="quiet-link" onClick={onAdmin}>Вход для сотрудников</button></footer>
  </div>
}
