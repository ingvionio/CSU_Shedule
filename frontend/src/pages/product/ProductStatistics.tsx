import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { BarChart3, CalendarDays, ChevronDown, ChevronLeft, LogOut, Search, Users } from 'lucide-react'

import { clearProductSession, readProductSession, writeProductSession } from '../../api/cache'
import { ApiError, api } from '../../api/client'
import type { AdminSession, ProductSummary, ProductUserFilters } from '../../api/types'
import { AreaChart } from './charts'
import { coursesOf } from './courses'
import {
  COUNT_GROUPS, FEATURE_LABELS, conversion, eventLabel, formatDateTime, formatDay, percent, platformLabel,
} from './labels'
import { PRESETS, periodError, presetPeriod, previousPeriod, todayLocal, type Period } from './period'
import './product.css'

const PAGE = 50

type Route = { tab: 'overview' } | { tab: 'users' } | { tab: 'user'; id: number }

/** Разделы ЛК в hash: #/users, #/users/12 — ссылку на пользователя можно переслать. */
function routeFromHash(hash: string): Route {
  const match = hash.match(/^#\/users(?:\/(\d+))?$/)
  if (!match) return { tab: 'overview' }
  return match[1] ? { tab: 'user', id: Number(match[1]) } : { tab: 'users' }
}

function useRoute(): [Route, (next: string) => void] {
  const [route, setRoute] = useState(() => routeFromHash(window.location.hash))
  useEffect(() => {
    const onHash = () => {
      setRoute(routeFromHash(window.location.hash))
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return [route, (next) => { window.location.hash = next }]
}

/** ЛК продукта: статистика для разработчиков и менеджера продукта. Открывается по /statistic. Тёмная тема. */
export function ProductStatistics() {
  const [session, setSession] = useState<AdminSession | null>(() => readProductSession())
  useEffect(() => {
    document.body.classList.add('pl-body')
    return () => document.body.classList.remove('pl-body')
  }, [])
  const login = (next: AdminSession) => {
    writeProductSession(next)
    setSession(next)
  }
  const logout = useCallback(() => {
    clearProductSession()
    setSession(null)
  }, [])

  return <div className="pl-root">{session ? <Shell token={session.token} onLogout={logout} /> : <Login onLogin={login} />}</div>
}

function Login({ onLogin }: { onLogin: (session: AdminSession) => void }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const response = await api.productLogin(login.trim(), password)
      onLogin({ token: response.access_token, expires_at: response.expires_at })
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="pl-login">
      <form className="pl-card pl-login-card" onSubmit={submit}>
        <div className="pl-brand"><span className="pl-logo">ИИТ</span>Расписание · продукт</div>
        <h1>Вход</h1>
        <label className="pl-field">Логин
          <input className="pl-input" autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} />
        </label>
        <label className="pl-field">Пароль
          <input className="pl-input" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p className="pl-error" role="alert">{error}</p>}
        <button className="pl-button pl-button-primary" disabled={busy || !login.trim() || !password}>{busy ? 'Входим…' : 'Войти'}</button>
      </form>
    </main>
  )
}

/** 401 — токен истёк или сменился секрет: возвращаемся к форме входа. */
function useSessionGuard(error: unknown, onLogout: () => void) {
  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) onLogout()
  }, [error, onLogout])
}

function ErrorNote({ error }: { error: unknown }) {
  if (!error || (error instanceof ApiError && error.status === 401)) return null
  return <div className="pl-note pl-note-error">{(error as Error).message}</div>
}

function Shell({ token, onLogout }: { token: string; onLogout: () => void }) {
  const [route, go] = useRoute()
  const [period, setPeriod] = useState<Period>(() => presetPeriod('month'))
  const nav = (tab: 'overview' | 'users', label: string, icon: ReactNode, href: string) => {
    const active = tab === 'overview' ? route.tab === 'overview' : route.tab !== 'overview'
    return (
      <a href={href} className={active ? 'active' : ''} aria-current={active ? 'page' : undefined}
        onClick={(event) => { event.preventDefault(); go(href) }}>
        {icon}{label}
      </a>
    )
  }

  return (
    <div className="pl-shell">
      <aside className="pl-sidebar">
        <div className="pl-brand"><span className="pl-logo">ИИТ</span>Расписание</div>
        <nav aria-label="Разделы">
          {nav('overview', 'Обзор', <BarChart3 size={16} />, '#/')}
          {nav('users', 'Пользователи', <Users size={16} />, '#/users')}
        </nav>
        <button className="pl-sidebar-logout" onClick={onLogout}><LogOut size={15} />Выйти</button>
      </aside>
      <main className="pl-main">
        {route.tab === 'overview' && <Overview token={token} period={period} onPeriod={setPeriod} onLogout={onLogout} />}
        {route.tab === 'users' && <UsersPage token={token} onLogout={onLogout} onOpen={(id) => go(`#/users/${id}`)} />}
        {route.tab === 'user' && <UserPage token={token} userId={route.id} onLogout={onLogout} onBack={() => go('#/users')} />}
      </main>
    </div>
  )
}

/* --- Период: кнопка с выпадающим списком, как в обычных CRM --- */

function PeriodPicker({ period, onChange }: { period: Period; onChange: (period: Period) => void }) {
  const [open, setOpen] = useState(false)
  const [start, setStart] = useState(period.start)
  const [end, setEnd] = useState(period.end)
  const box = useRef<HTMLDivElement>(null)
  const error = periodError(start, end)
  const label = period.preset === 'custom'
    ? `${formatDay(period.start)} — ${formatDay(period.end)}`
    : PRESETS.find((preset) => preset.id === period.preset)?.label

  useEffect(() => {
    if (!open) return
    setStart(period.start)
    setEnd(period.end)
    const onDown = (event: PointerEvent) => { if (!box.current?.contains(event.target as Node)) setOpen(false) }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, period.start, period.end])

  const apply = (event: FormEvent) => {
    event.preventDefault()
    if (error) return
    onChange({ start, end, preset: 'custom' })
    setOpen(false)
  }

  return (
    <div className="pl-period" ref={box}>
      <button className="pl-button" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)}>
        <CalendarDays size={15} />{label}<ChevronDown size={15} />
      </button>
      {open && (
        <div className="pl-popover" role="dialog" aria-label="Период">
          <ul>
            {PRESETS.map((preset) => (
              <li key={preset.id}>
                <button className={period.preset === preset.id ? 'active' : ''}
                  onClick={() => { onChange(presetPeriod(preset.id)); setOpen(false) }}>{preset.label}</button>
              </li>
            ))}
          </ul>
          <form onSubmit={apply}>
            <span className="pl-popover-title">Свой период</span>
            <label className="pl-field">С<input className="pl-input" type="date" value={start} max={todayLocal()} onChange={(event) => setStart(event.target.value)} /></label>
            <label className="pl-field">По<input className="pl-input" type="date" value={end} max={todayLocal()} onChange={(event) => setEnd(event.target.value)} /></label>
            {error && <span className="pl-error">{error}</span>}
            <button className="pl-button pl-button-primary" disabled={Boolean(error)}>Применить</button>
          </form>
        </div>
      )}
    </div>
  )
}

/* --- Обзор --- */

function Delta({ current, previous }: { current: number; previous: number | undefined }) {
  if (previous === undefined) return null
  if (previous === 0) return <span className="pl-delta">{current > 0 ? 'новое' : '—'}</span>
  const change = Math.round(((current - previous) / previous) * 100)
  const tone = change > 0 ? 'up' : change < 0 ? 'down' : ''
  return <span className={`pl-delta ${tone}`}>{change > 0 ? '↑' : change < 0 ? '↓' : ''}{Math.abs(change)}%</span>
}

function Kpi({ label, value, previous, hint }: { label: string; value: number | string; previous?: number; hint?: string }) {
  return (
    <div className="pl-kpi">
      <span className="pl-kpi-label">{label}</span>
      <div className="pl-kpi-value">
        <strong>{value}</strong>
        {typeof value === 'number' && <Delta current={value} previous={previous} />}
      </div>
      {hint && <span className="pl-kpi-hint">{hint}</span>}
    </div>
  )
}

/** Метрики графика и их итог за период: у «активных» и «лендинга» — уникальные за весь период, а не сумма дней. */
const METRICS = [
  { key: 'dau', label: 'Активные', total: (data: ProductSummary) => data.active_users, unit: 'уникальных за период' },
  { key: 'new_users', label: 'Новые', total: (data: ProductSummary) => data.users_new, unit: 'за период' },
  { key: 'landing_devices', label: 'Лендинг', total: (data: ProductSummary) => data.funnel.landing_view, unit: 'устройств за период' },
] as const

function Overview({ token, period, onPeriod, onLogout }: {
  token: string; period: Period; onPeriod: (period: Period) => void; onLogout: () => void
}) {
  const previous = previousPeriod(period)
  const summary = useQuery({
    queryKey: ['product-summary', period.start, period.end, token],
    queryFn: () => api.productSummary(token, period.start, period.end),
    staleTime: 60 * 1000,
    placeholderData: (data) => data,
  })
  const before = useQuery({
    queryKey: ['product-summary', previous.start, previous.end, token],
    queryFn: () => api.productSummary(token, previous.start, previous.end),
    staleTime: 5 * 60 * 1000,
  })
  useSessionGuard(summary.error, onLogout)

  return (
    <>
      <header className="pl-header">
        <div>
          <h1>Обзор</h1>
          <p>Изменение — к предыдущему периоду той же длины</p>
        </div>
        <PeriodPicker period={period} onChange={onPeriod} />
      </header>
      <ErrorNote error={summary.error} />
      {summary.isLoading && <div className="pl-note">Загружаем…</div>}
      {summary.data && <OverviewBody data={summary.data} previous={before.data} />}
    </>
  )
}

function OverviewBody({ data, previous }: { data: ProductSummary; previous: ProductSummary | undefined }) {
  const [metric, setMetric] = useState<(typeof METRICS)[number]['key']>('dau')
  const funnel = [
    ['Открыли лендинг', data.funnel.landing_view],
    ['Открыли форму входа', data.funnel.login_click],
    ['Отправили форму входа', data.funnel.login_submit],
    ['Вошли', data.funnel.login_success],
  ] as const
  const funnelTop = Math.max(funnel[0][1], 1)
  const current = METRICS.find((item) => item.key === metric)!
  const platforms = Object.entries(data.by_platform).sort((a, b) => b[1] - a[1])

  const partial = data.tracking_since !== null && data.tracking_since > data.start_date

  return (
    <>
      {data.tracking_since === null && <div className="pl-note">Событий пока нет: воронка, функции и платформы начнут заполняться после первых заходов.</div>}
      {partial && (
        <div className="pl-note">
          События собираются с {formatDay(data.tracking_since!)}. До этого воронка, функции и платформы пустые, а активность
          видна только по датам входа из профилей.
        </div>
      )}
      <section className="pl-kpis" aria-label="Ключевые показатели">
        <Kpi label="Активные пользователи" value={data.active_users} previous={previous?.active_users} hint="заходили в приложение" />
        <Kpi label="Новые пользователи" value={data.users_new} previous={previous?.users_new} hint="вошли впервые" />
        <Kpi label="Всего пользователей" value={data.users_total} hint="на сегодня" />
        <Kpi label="С уведомлениями" value={percent(data.users_with_push, data.users_total)} hint={`${data.users_with_push} из ${data.users_total}`} />
      </section>

      <section className="pl-card">
        <div className="pl-card-head">
          <div className="pl-chart-total">
            <h2>{current.label}</h2>
            <strong>{current.total(data)}</strong>
            <span className="pl-muted">{current.unit}</span>
          </div>
          <div className="pl-segmented" role="tablist" aria-label="Метрика">
            {METRICS.map((item) => (
              <button key={item.key} role="tab" aria-selected={metric === item.key} className={metric === item.key ? 'active' : ''}
                onClick={() => setMetric(item.key)}>{item.label}</button>
            ))}
          </div>
        </div>
        <AreaChart label={current.label}
          dates={data.daily.map((day) => day.date)} values={data.daily.map((day) => day[metric])} />
      </section>

      <div className="pl-grid-2">
        <section className="pl-card">
          <div className="pl-card-head"><h2>Воронка входа</h2><span className="pl-muted">устройства; шаг — среди прошедших предыдущий</span></div>
          <table className="pl-table">
            <thead><tr><th>Шаг</th><th className="num">Устройств</th><th className="num">Конверсия</th></tr></thead>
            <tbody>
              {funnel.map(([label, value], index) => (
                <tr key={label}>
                  <td>
                    {label}
                    <span className="pl-meter"><span style={{ width: `${(value / funnelTop) * 100}%` }} /></span>
                  </td>
                  <td className="num">{value}</td>
                  <td className="num pl-muted">{index === 0 ? '—' : conversion(value, funnel[index - 1][1])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table className="pl-table">
            <tbody>
              <tr><td>Всего вошли за период</td><td className="num">{data.funnel.login_any}</td><td className="num pl-muted">устройств</td></tr>
              <tr>
                <td>из них без лендинга <span className="pl-muted">— ссылка, уведомление, лендинг раньше периода</span></td>
                <td className="num">{data.funnel.login_without_landing}</td><td className="num pl-muted">устройств</td>
              </tr>
            </tbody>
          </table>
          <p className="pl-footnote">
            Неудачных входов: неверный пароль — {data.login_failures.auth}, группа не определилась — {data.login_failures.group}, Moodle недоступен — {data.login_failures.other}
          </p>
        </section>

        <section className="pl-card">
          <div className="pl-card-head"><h2>Функции</h2><span className="pl-muted">за период</span></div>
          <table className="pl-table">
            <thead><tr><th>Действие</th><th className="num">Студентов</th><th className="num">Раз</th></tr></thead>
            <tbody>
              {data.features.map((feature) => (
                <tr key={feature.name}>
                  <td>{FEATURE_LABELS[feature.name] ?? feature.name}</td>
                  <td className="num">{feature.users}</td>
                  <td className="num pl-muted">{feature.events}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <div className="pl-grid-3">
        <section className="pl-card">
          <div className="pl-card-head"><h2>Удержание</h2></div>
          <table className="pl-table">
            <tbody>
              {data.retention.map((row) => (
                <tr key={row.week}>
                  <td>Вернулись на {row.week}-й неделе</td>
                  <td className="num">{percent(row.returned, row.eligible)}</td>
                  <td className="num pl-muted">{row.returned} из {row.eligible}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="pl-footnote">Новые за период; учтены только те, у кого эта неделя уже прошла.</p>
        </section>
        <section className="pl-card">
          <div className="pl-card-head"><h2>Платформы</h2><span className="pl-muted">активные</span></div>
          <table className="pl-table">
            <tbody>
              {platforms.map(([platform, value]) => (
                <tr key={platform}>
                  <td>{platformLabel(platform)}</td>
                  <td className="num">{value}</td>
                  <td className="num pl-muted">{percent(value, data.active_users)}</td>
                </tr>
              ))}
              {platforms.length === 0 && <tr><td className="pl-muted">Нет активных за период</td></tr>}
            </tbody>
          </table>
        </section>
        <section className="pl-card">
          <div className="pl-card-head"><h2>Android</h2></div>
          <table className="pl-table">
            <tbody>
              <tr><td>Скачиваний APK</td><td className="num">{data.apk_downloads}</td></tr>
              <tr><td>Установок за период</td><td className="num">{data.apk_installs}</td></tr>
              <tr><td>Установок всего</td><td className="num">{data.apk_installs_total}</td></tr>
            </tbody>
          </table>
        </section>
      </div>

      <section className="pl-card">
        <div className="pl-card-head"><h2>Курсы и группы</h2><span className="pl-muted">сколько студентов уже вошли; численность групп приложению неизвестна</span></div>
        <div className="pl-scroll">
          <table className="pl-table">
            <thead><tr><th>Курс / группа</th><th className="num">С профилем</th><th className="num">Новые</th><th className="num">Активны</th></tr></thead>
            {coursesOf(data.groups).map((course) => (
              <tbody key={course.key} className="pl-course">
                <tr className="pl-course-row">
                  <td>{course.title}</td>
                  <td className="num">{course.users}</td>
                  <td className="num">{course.new}</td>
                  <td className="num">{course.active}</td>
                </tr>
                {course.groups.map((group) => (
                  <tr key={group.id} className={group.users === 0 ? 'pl-dim' : ''}>
                    <td className="pl-indent">{group.name}</td>
                    <td className="num">{group.users}</td>
                    <td className="num">{group.new}</td>
                    <td className="num">{group.active}</td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      </section>
    </>
  )
}

/* --- Пользователи --- */

const EMPTY_FILTERS: ProductUserFilters = { sort: 'last_seen', order: 'desc', limit: PAGE, offset: 0 }

type SortKey = ProductUserFilters['sort']

/** Заголовок столбца, как в проводнике: щелчок сортирует, повторный — в обратную сторону. */
function SortHeader({ label, column, filters, onSort, className }: {
  label: string; column: SortKey; filters: ProductUserFilters; onSort: (column: SortKey) => void; className?: string
}) {
  const active = filters.sort === column
  return (
    <th className={className} aria-sort={active ? (filters.order === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className={`pl-sort ${active ? 'active' : ''}`} onClick={() => onSort(column)}>
        {label}<span aria-hidden="true">{active ? (filters.order === 'asc' ? '▲' : '▼') : ''}</span>
      </button>
    </th>
  )
}

function UsersPage({ token, onLogout, onOpen }: { token: string; onLogout: () => void; onOpen: (id: number) => void }) {
  const [draft, setDraft] = useState<ProductUserFilters>(EMPTY_FILTERS)
  const [filters, setFilters] = useState<ProductUserFilters>(EMPTY_FILTERS)
  const groups = useQuery({ queryKey: ['groups'], queryFn: () => api.groups(), staleTime: 60 * 60 * 1000 })
  const users = useQuery({
    queryKey: ['product-users', filters, token],
    queryFn: () => api.productUsers(token, filters),
    placeholderData: (data) => data,
  })
  useSessionGuard(users.error, onLogout)
  const total = users.data?.total ?? 0
  const set = (patch: Partial<ProductUserFilters>) => setDraft((current) => ({ ...current, ...patch }))
  const apply = (event: FormEvent) => {
    event.preventDefault()
    setFilters({ ...draft, offset: 0 })
  }
  const reset = () => {
    setDraft(EMPTY_FILTERS)
    setFilters(EMPTY_FILTERS)
  }
  const page = (offset: number) => setFilters((current) => ({ ...current, offset }))
  const sortBy = (column: SortKey) => {
    const order = filters.sort === column
      ? (filters.order === 'asc' ? 'desc' : 'asc')
      : (column === 'name' || column === 'group' || column === 'platform' ? 'asc' : 'desc')
    setDraft((current) => ({ ...current, sort: column, order }))
    setFilters((current) => ({ ...current, sort: column, order, offset: 0 }))
  }

  return (
    <>
      <header className="pl-header">
        <div>
          <h1>Пользователи</h1>
          <p>{total} {total === 1 ? 'студент' : 'студентов'} по фильтрам</p>
        </div>
      </header>
      <form className="pl-card pl-filters" onSubmit={apply}>
        <label className="pl-field pl-filter-search">Поиск
          <span className="pl-input-icon"><Search size={15} />
            <input className="pl-input" value={draft.q ?? ''} placeholder="ФИО" onChange={(event) => set({ q: event.target.value })} />
          </span>
        </label>
        <label className="pl-field">Группа
          <select className="pl-input" value={draft.group_id ?? ''} onChange={(event) => set({ group_id: event.target.value ? Number(event.target.value) : null })}>
            <option value="">Все</option>
            {groups.data?.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
          </select>
        </label>
        <label className="pl-field">Платформа
          <select className="pl-input" value={draft.platform ?? ''} onChange={(event) => set({ platform: (event.target.value || null) as ProductUserFilters['platform'] })}>
            <option value="">Все</option>
            <option value="web">{platformLabel('web')}</option>
            <option value="pwa">{platformLabel('pwa')}</option>
            <option value="apk">{platformLabel('apk')}</option>
            <option value="unknown">{platformLabel('unknown')}</option>
          </select>
        </label>
        <div className="pl-field" role="group" aria-labelledby="f-seen">
          <span id="f-seen">Последний заход</span>
          <span className="pl-range">
            <input className="pl-input" type="date" aria-label="Последний заход с" value={draft.last_seen_from ?? ''} onChange={(event) => set({ last_seen_from: event.target.value })} />
            <input className="pl-input" type="date" aria-label="Последний заход по" value={draft.last_seen_to ?? ''} onChange={(event) => set({ last_seen_to: event.target.value })} />
          </span>
        </div>
        <div className="pl-field" role="group" aria-labelledby="f-created">
          <span id="f-created">Первый вход</span>
          <span className="pl-range">
            <input className="pl-input" type="date" aria-label="Первый вход с" value={draft.created_from ?? ''} onChange={(event) => set({ created_from: event.target.value })} />
            <input className="pl-input" type="date" aria-label="Первый вход по" value={draft.created_to ?? ''} onChange={(event) => set({ created_to: event.target.value })} />
          </span>
        </div>
        <div className="pl-filter-actions">
          <button className="pl-button pl-button-primary">Применить</button>
          <button type="button" className="pl-button" onClick={reset}>Сбросить</button>
        </div>
      </form>

      <ErrorNote error={users.error} />
      {users.data && (
        <section className="pl-card pl-card-flush">
          <div className="pl-scroll">
            <table className="pl-table pl-table-rows">
              <thead>
                <tr>
                  <SortHeader label="Студент" column="name" filters={filters} onSort={sortBy} />
                  <SortHeader label="Группа" column="group" filters={filters} onSort={sortBy} />
                  <SortHeader label="Последний заход" column="last_seen" filters={filters} onSort={sortBy} />
                  <SortHeader label="Первый вход" column="created" filters={filters} onSort={sortBy} />
                  <SortHeader label="Дней за 30" column="active_days" filters={filters} onSort={sortBy} className="num" />
                  <SortHeader label="Платформа" column="platform" filters={filters} onSort={sortBy} />
                </tr>
              </thead>
              <tbody>
                {users.data.items.map((user) => (
                  <tr key={user.id} onClick={() => onOpen(user.id)}>
                    <td><a href={`#/users/${user.id}`} onClick={(event) => { event.preventDefault(); onOpen(user.id) }}>{user.full_name}</a></td>
                    <td className="pl-muted pl-nowrap">{user.group?.name ?? '—'}</td>
                    <td className="pl-nowrap">{formatDateTime(user.last_seen_at)}</td>
                    <td className="pl-muted pl-nowrap">{formatDateTime(user.created_at)}</td>
                    <td className="num">{user.active_days_30}</td>
                    <td className="pl-muted">{platformLabel(user.last_platform)}</td>
                  </tr>
                ))}
                {users.data.items.length === 0 && <tr><td colSpan={6} className="pl-muted">Никого не нашли</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="pl-pager">
            <span className="pl-muted">{total === 0 ? '0' : `${filters.offset + 1}–${Math.min(filters.offset + PAGE, total)}`} из {total}</span>
            <button className="pl-button" disabled={filters.offset === 0} onClick={() => page(Math.max(filters.offset - PAGE, 0))}>Назад</button>
            <button className="pl-button" disabled={filters.offset + PAGE >= total} onClick={() => page(filters.offset + PAGE)}>Дальше</button>
          </div>
        </section>
      )}
    </>
  )
}

function UserPage({ token, userId, onLogout, onBack }: { token: string; userId: number; onLogout: () => void; onBack: () => void }) {
  const card = useQuery({ queryKey: ['product-user', userId, token], queryFn: () => api.productUser(token, userId) })
  const events = useInfiniteQuery({
    queryKey: ['product-user-events', userId, token],
    queryFn: ({ pageParam }) => api.productUserEvents(token, userId, pageParam),
    initialPageParam: null as number | null,
    getNextPageParam: (page) => page.next_before,
  })
  useSessionGuard(card.error ?? events.error, onLogout)
  const items = events.data?.pages.flatMap((page) => page.items) ?? []
  const user = card.data?.user

  return (
    <>
      <header className="pl-header">
        <div>
          <a className="pl-breadcrumb" href="#/users" onClick={(event) => { event.preventDefault(); onBack() }}><ChevronLeft size={14} />Пользователи</a>
          <h1>{user?.full_name ?? 'Пользователь'}</h1>
          {user && <p>{user.group ? `${user.group.name}, ${user.group.course} курс` : 'Группа не указана'}</p>}
        </div>
      </header>
      <ErrorNote error={card.error} />
      {user && card.data && (
        <>
          <section className="pl-kpis pl-kpis-compact" aria-label="Профиль">
            <Kpi label="Первый вход" value={formatDateTime(user.created_at)} />
            <Kpi label="Последний заход" value={formatDateTime(user.last_seen_at)} />
            <Kpi label="Дней за 30" value={String(user.active_days_30)} />
            <Kpi label="Платформа" value={platformLabel(user.last_platform)} />
            <Kpi label="Уведомления" value={card.data.push_enabled ? 'Включены' : 'Выключены'} />
          </section>
          <section className="pl-card">
            <div className="pl-card-head"><h2>Сводка за всё время</h2></div>
            <div className="pl-summary-groups">
              {COUNT_GROUPS.map((group) => (
                <table key={group.title} className="pl-table">
                  <thead><tr><th>{group.title}</th><th className="num">Раз</th></tr></thead>
                  <tbody>
                    {group.events.map((name) => (
                      <tr key={name} className={card.data.counts[name] ? '' : 'pl-dim'}>
                        <td>{eventLabel(name)}</td><td className="num">{card.data.counts[name] ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}
            </div>
          </section>
        </>
      )}

      <section className="pl-card pl-card-flush">
        <div className="pl-card-head"><h2>Действия</h2></div>
        {events.data && items.length === 0 && <p className="pl-footnote">Событий пока нет: студент не заходил после включения статистики.</p>}
        {items.length > 0 && (
          <div className="pl-scroll">
            <table className="pl-table">
              <thead><tr><th>Когда</th><th>Действие</th><th>Платформа</th><th>Версия</th></tr></thead>
              <tbody>
                {items.map((event) => (
                  <tr key={event.id}>
                    <td className="pl-muted pl-nowrap">{formatDateTime(event.occurred_at)}</td>
                    <td>{eventLabel(event.name)}{event.detail && <span className="pl-muted"> · «{event.detail}»</span>}</td>
                    <td className="pl-muted">{platformLabel(event.platform)}</td>
                    <td className="pl-muted">{event.app_version ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {events.hasNextPage && (
          <div className="pl-pager">
            <button className="pl-button" onClick={() => events.fetchNextPage()} disabled={events.isFetchingNextPage}>
              {events.isFetchingNextPage ? 'Загружаем…' : 'Показать раньше'}
            </button>
          </div>
        )}
      </section>
    </>
  )
}
