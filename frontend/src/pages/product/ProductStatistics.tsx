import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { ArrowLeft, CalendarRange, LogIn, LogOut, RefreshCw, Search } from 'lucide-react'

import { clearProductSession, readProductSession, writeProductSession } from '../../api/cache'
import { ApiError, api } from '../../api/client'
import type { AdminSession, ProductSummary, ProductUserFilters } from '../../api/types'
import { BarList, ColumnChart, LineChart, SERIES_COLORS } from './charts'
import {
  COUNT_GROUPS, FEATURE_LABELS, conversion, eventLabel, formatDateTime, formatDay, percent, platformLabel,
} from './labels'
import { PRESETS, periodError, presetPeriod, todayLocal, type Period } from './period'

const PAGE = 50

type Route = { tab: 'overview' } | { tab: 'users' } | { tab: 'user'; id: number }

/** Вкладки ЛК в hash: #/users, #/users/12 — ссылку на пользователя можно переслать. */
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

/** ЛК продукта: статистика для разработчиков и менеджера продукта. Открывается по /statistic. */
export function ProductStatistics() {
  const [session, setSession] = useState<AdminSession | null>(() => readProductSession())
  const login = (next: AdminSession) => {
    writeProductSession(next)
    setSession(next)
  }
  const logout = useCallback(() => {
    clearProductSession()
    setSession(null)
  }, [])

  return (
    <main className="product-page">
      {session ? <Workspace token={session.token} onLogout={logout} /> : <ProductLogin onLogin={login} />}
    </main>
  )
}

function ProductLogin({ onLogin }: { onLogin: (session: AdminSession) => void }) {
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
    <form className="screen-card selection-screen admin-login product-login" onSubmit={submit}>
      <div className="eyebrow">ЛК ПРОДУКТА</div>
      <h1>Статистика приложения</h1>
      <p className="muted">Вход для команды разработки. Это не кабинет методиста.</p>
      <label className="field-label" htmlFor="product-login">Логин</label>
      <input id="product-login" className="text-field" autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} />
      <label className="field-label" htmlFor="product-password">Пароль</label>
      <input id="product-password" className="text-field" type="password" autoComplete="current-password"
        value={password} onChange={(event) => setPassword(event.target.value)} />
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button button-primary full" disabled={busy || !login.trim() || !password}>
        <LogIn size={17} />{busy ? 'Входим…' : 'Войти'}
      </button>
    </form>
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
  return <div className="state-note error-note">{(error as Error).message}</div>
}

function Workspace({ token, onLogout }: { token: string; onLogout: () => void }) {
  const [route, go] = useRoute()
  return (
    <div className="product-dashboard">
      <header className="product-header">
        <div>
          <div className="eyebrow">ЛК ПРОДУКТА · РАСПИСАНИЕ ИИТ</div>
          <h1>Статистика</h1>
        </div>
        <button className="button button-secondary" onClick={onLogout}><LogOut size={16} />Выйти</button>
      </header>
      <nav className="admin-target-tabs product-tabs" aria-label="Разделы">
        <button className={route.tab === 'overview' ? 'active' : ''} aria-current={route.tab === 'overview' ? 'page' : undefined} onClick={() => go('#/')}>Обзор</button>
        <button className={route.tab !== 'overview' ? 'active' : ''} aria-current={route.tab !== 'overview' ? 'page' : undefined} onClick={() => go('#/users')}>Пользователи</button>
      </nav>
      {route.tab === 'overview' && <Overview token={token} onLogout={onLogout} onOpenUser={(id) => go(`#/users/${id}`)} />}
      {route.tab === 'users' && <UsersTab token={token} onLogout={onLogout} onOpenUser={(id) => go(`#/users/${id}`)} />}
      {route.tab === 'user' && <UserPage token={token} userId={route.id} onLogout={onLogout} onBack={() => go('#/users')} />}
    </div>
  )
}

/* --- Период --- */

function PeriodPicker({ period, onChange }: { period: Period; onChange: (period: Period) => void }) {
  const [open, setOpen] = useState(period.preset === 'custom')
  const [start, setStart] = useState(period.start)
  const [end, setEnd] = useState(period.end)
  const error = periodError(start, end)
  const today = todayLocal()

  const apply = (event: FormEvent) => {
    event.preventDefault()
    if (!error) onChange({ start, end, preset: 'custom' })
  }

  return (
    <div className="product-period">
      <div className="product-presets" role="group" aria-label="Период">
        {PRESETS.map((preset) => (
          <button key={preset.id} type="button" aria-pressed={period.preset === preset.id}
            className={period.preset === preset.id ? 'active' : ''}
            onClick={() => { setOpen(false); onChange(presetPeriod(preset.id)) }}>
            {preset.label}
          </button>
        ))}
        <button type="button" aria-pressed={period.preset === 'custom'} aria-expanded={open}
          className={period.preset === 'custom' ? 'active' : ''} onClick={() => setOpen(!open)}>
          <CalendarRange size={15} />Свой период
        </button>
      </div>
      {open && (
        <form className="product-custom-period" onSubmit={apply}>
          <label>С<input type="date" className="text-field" value={start} max={today} onChange={(event) => setStart(event.target.value)} /></label>
          <label>По<input type="date" className="text-field" value={end} max={today} onChange={(event) => setEnd(event.target.value)} /></label>
          <button className="button button-primary" disabled={Boolean(error)}>Показать</button>
          {error && <span className="form-error">{error}</span>}
        </form>
      )}
      <p className="muted">{formatDay(period.start)} — {formatDay(period.end)} · время по Челябинску</p>
    </div>
  )
}

/* --- Обзор --- */

function Tile({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="product-tile">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )
}

function Overview({ token, onLogout, onOpenUser }: { token: string; onLogout: () => void; onOpenUser: (id: number) => void }) {
  const [period, setPeriod] = useState<Period>(() => presetPeriod('month'))
  const summary = useQuery({
    queryKey: ['product-summary', period.start, period.end, token],
    queryFn: () => api.productSummary(token, period.start, period.end),
    staleTime: 60 * 1000,
    placeholderData: (previous) => previous,
  })
  useSessionGuard(summary.error, onLogout)

  return (
    <>
      <div className="product-toolbar">
        <PeriodPicker period={period} onChange={setPeriod} />
        <button className="button button-secondary" onClick={() => summary.refetch()} disabled={summary.isFetching}>
          <RefreshCw size={16} />Обновить
        </button>
      </div>
      {summary.isLoading && <div className="state-note">Считаем статистику…</div>}
      <ErrorNote error={summary.error} />
      {summary.data && <SummaryView data={summary.data} onOpenUser={onOpenUser} />}
    </>
  )
}

function SummaryView({ data }: { data: ProductSummary; onOpenUser: (id: number) => void }) {
  const funnel = [
    { label: 'Открыли лендинг', value: data.funnel.landing_view },
    { label: 'Нажали «Войти через Moodle»', value: data.funnel.login_click },
    { label: 'Отправили форму', value: data.funnel.login_submit },
    { label: 'Вошли', value: data.funnel.login_success },
  ].map((step, index, steps) => ({ ...step, note: index > 0 ? `${conversion(step.value, steps[index - 1].value)} от шага ${index}` : undefined }))
  const failures = data.login_failures.auth + data.login_failures.group + data.login_failures.other
  const dates = data.daily.map((day) => day.date)
  const series = [
    { key: 'dau', label: 'Активные', values: data.daily.map((day) => day.dau) },
    { key: 'new', label: 'Новые', values: data.daily.map((day) => day.new_users) },
    { key: 'login', label: 'Входы', values: data.daily.map((day) => day.login_success) },
    { key: 'landing', label: 'Лендинг (устройства)', values: data.daily.map((day) => day.landing_devices) },
  ].map((item, index) => ({ ...item, color: SERIES_COLORS[index] }))

  return (
    <>
      <section className="product-section" aria-labelledby="ov-users">
        <h2 id="ov-users">Пользователи</h2>
        <div className="product-tiles">
          <Tile label="Всего пользователей" value={data.users_total} hint="студентов с профилем" />
          <Tile label="Новые за период" value={data.users_new} />
          <Tile label="Активные за период" value={data.active_users} />
          <Tile label="DAU" value={data.dau} hint={`за ${formatDay(data.end_date)}`} />
          <Tile label="WAU" value={data.wau} hint="7 дней по конец периода" />
          <Tile label="MAU" value={data.mau} hint="30 дней по конец периода" />
          <Tile label="С уведомлениями" value={percent(data.users_with_push, data.users_total)} hint={`${data.users_with_push} из ${data.users_total} сейчас`} />
        </div>
      </section>

      <section className="product-section" aria-labelledby="ov-daily">
        <h2 id="ov-daily">По дням</h2>
        <LineChart title="Активность по дням" dates={dates} series={series} />
      </section>

      <div className="product-columns">
        <section className="product-section" aria-labelledby="ov-funnel">
          <h2 id="ov-funnel">Воронка входа</h2>
          <p className="muted">Уникальные устройства за период.</p>
          <ColumnChart title="Воронка входа" columns={funnel} />
          <p className="muted">
            Неудачных входов: {failures}
            {failures > 0 && ` — неверный логин или пароль ${data.login_failures.auth}, группа не определилась ${data.login_failures.group}, Moodle недоступен или ошибка ${data.login_failures.other}`}
          </p>
        </section>

        <section className="product-section" aria-labelledby="ov-retention">
          <h2 id="ov-retention">Удержание</h2>
          <p className="muted">Новые за период, которые вернулись через неделю после первого входа. Считаются только те, у кого эта неделя уже прошла.</p>
          <div className="product-tiles">
            {data.retention.map((row) => (
              <Tile key={row.week} label={`${row.week}-я неделя`} value={percent(row.returned, row.eligible)}
                hint={row.eligible ? `${row.returned} из ${row.eligible}` : 'пока некого считать'} />
            ))}
          </div>
          <h3 className="product-subtitle">Платформы активных</h3>
          <BarList title="Платформы активных пользователей"
            rows={Object.entries(data.by_platform).sort((a, b) => b[1] - a[1]).map(([platform, value]) => ({ key: platform, label: platformLabel(platform), value }))} />
          {Object.keys(data.by_platform).length === 0 && <p className="muted">Нет активных за период.</p>}
        </section>
      </div>

      <section className="product-section" aria-labelledby="ov-features">
        <h2 id="ov-features">Чем пользуются</h2>
        <p className="muted">Уникальные студенты за период; в подсказке и справа — сколько раз всего.</p>
        <BarList title="Использование функций"
          rows={data.features.map((feature) => ({
            key: feature.name,
            label: FEATURE_LABELS[feature.name] ?? feature.name,
            value: feature.users,
            caption: `${feature.users} чел. · ${feature.events} раз`,
          }))} />
      </section>

      <div className="product-columns">
        <section className="product-section" aria-labelledby="ov-apk">
          <h2 id="ov-apk">Android</h2>
          <div className="product-tiles">
            <Tile label="Скачиваний APK" value={data.apk_downloads} hint="открытий /download" />
            <Tile label="Установок за период" value={data.apk_installs} hint="первый запуск APK" />
            <Tile label="Установок всего" value={data.apk_installs_total} />
          </div>
        </section>

        <section className="product-section" aria-labelledby="ov-groups">
          <h2 id="ov-groups">Охват групп</h2>
          <p className="muted">Сколько студентов группы уже вошли. Численность групп приложению неизвестна.</p>
          <div className="import-table-scroll product-groups">
            <table className="import-table product-table">
              <thead><tr><th>Группа</th><th>Курс</th><th>С профилем</th><th>Новые</th><th>Активны</th></tr></thead>
              <tbody>
                {data.groups.map((group) => (
                  <tr key={group.id} className={group.users === 0 ? 'muted-row' : ''}>
                    <td>{group.name}</td><td>{group.course}</td><td>{group.users}</td><td>{group.new}</td><td>{group.active}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  )
}

/* --- Пользователи --- */

const EMPTY_FILTERS: ProductUserFilters = { sort: 'last_seen', limit: PAGE, offset: 0 }

function UsersTab({ token, onLogout, onOpenUser }: { token: string; onLogout: () => void; onOpenUser: (id: number) => void }) {
  const [draft, setDraft] = useState<ProductUserFilters>(EMPTY_FILTERS)
  const [filters, setFilters] = useState<ProductUserFilters>(EMPTY_FILTERS)
  const groups = useQuery({ queryKey: ['groups'], queryFn: () => api.groups(), staleTime: 60 * 60 * 1000 })
  const users = useQuery({
    queryKey: ['product-users', filters, token],
    queryFn: () => api.productUsers(token, filters),
    placeholderData: (previous) => previous,
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

  return (
    <section className="product-section" aria-labelledby="users-title">
      <h2 id="users-title">Пользователи</h2>
      <form className="product-filters" onSubmit={apply}>
        <label className="product-filter-wide">Поиск по ФИО
          <input className="text-field" value={draft.q ?? ''} onChange={(event) => set({ q: event.target.value })} placeholder="Например, Иванов" />
        </label>
        <label>Группа
          <select className="select-field" value={draft.group_id ?? ''} onChange={(event) => set({ group_id: event.target.value ? Number(event.target.value) : null })}>
            <option value="">Все группы</option>
            {groups.data?.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
          </select>
        </label>
        <label>Сортировка
          <select className="select-field" value={draft.sort} onChange={(event) => set({ sort: event.target.value as ProductUserFilters['sort'] })}>
            <option value="last_seen">Последний заход</option>
            <option value="created">Первый вход</option>
            <option value="name">ФИО</option>
          </select>
        </label>
        <div className="product-date-range" role="group" aria-labelledby="filter-last_seen">
          <span id="filter-last_seen">Последний заход</span>
          <div>
            <input type="date" className="text-field" aria-label="Последний заход с" value={draft.last_seen_from ?? ''} onChange={(event) => set({ last_seen_from: event.target.value })} />
            <span aria-hidden="true">—</span>
            <input type="date" className="text-field" aria-label="Последний заход по" value={draft.last_seen_to ?? ''} onChange={(event) => set({ last_seen_to: event.target.value })} />
          </div>
        </div>
        <div className="product-date-range" role="group" aria-labelledby="filter-created">
          <span id="filter-created">Первый вход</span>
          <div>
            <input type="date" className="text-field" aria-label="Первый вход с" value={draft.created_from ?? ''} onChange={(event) => set({ created_from: event.target.value })} />
            <span aria-hidden="true">—</span>
            <input type="date" className="text-field" aria-label="Первый вход по" value={draft.created_to ?? ''} onChange={(event) => set({ created_to: event.target.value })} />
          </div>
        </div>
        <div className="product-filter-actions">
          <button className="button button-primary"><Search size={16} />Найти</button>
          <button type="button" className="button button-secondary" onClick={reset}>Сбросить</button>
        </div>
      </form>

      <ErrorNote error={users.error} />
      {users.data && (
        <>
          <div className="import-table-scroll">
            <table className="import-table product-table">
              <thead>
                <tr><th>Студент</th><th>Группа</th><th>Последний заход</th><th>Первый вход</th><th>Дней за 30</th><th>Платформа</th></tr>
              </thead>
              <tbody>
                {users.data.items.map((user) => (
                  <tr key={user.id}>
                    <td><a className="product-user-link" href={`#/users/${user.id}`} onClick={(event) => { event.preventDefault(); onOpenUser(user.id) }}>{user.full_name}</a></td>
                    <td>{user.group ? `${user.group.name} · ${user.group.course} курс` : '—'}</td>
                    <td>{formatDateTime(user.last_seen_at)}</td>
                    <td>{formatDateTime(user.created_at)}</td>
                    <td>{user.active_days_30}</td>
                    <td>{platformLabel(user.last_platform)}</td>
                  </tr>
                ))}
                {users.data.items.length === 0 && <tr><td colSpan={6}>Никого не нашли</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="product-pager">
            <span className="muted">{total === 0 ? '0' : `${filters.offset + 1}–${Math.min(filters.offset + PAGE, total)}`} из {total}</span>
            <button className="button button-secondary" disabled={filters.offset === 0} onClick={() => page(Math.max(filters.offset - PAGE, 0))}>Назад</button>
            <button className="button button-secondary" disabled={filters.offset + PAGE >= total} onClick={() => page(filters.offset + PAGE)}>Дальше</button>
          </div>
        </>
      )}
    </section>
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
      <button className="button button-secondary product-back" onClick={onBack}><ArrowLeft size={16} />Все пользователи</button>
      <ErrorNote error={card.error} />
      {card.isLoading && <div className="state-note">Загружаем профиль…</div>}
      {user && card.data && (
        <section className="product-section" aria-labelledby="user-title">
          <h2 id="user-title">{user.full_name}</h2>
          <dl className="product-user-facts">
            <div><dt>Группа</dt><dd>{user.group ? `${user.group.name}, ${user.group.course} курс` : '—'}</dd></div>
            <div><dt>Первый вход</dt><dd>{formatDateTime(user.created_at)}</dd></div>
            <div><dt>Последний заход</dt><dd>{formatDateTime(user.last_seen_at)}</dd></div>
            <div><dt>Дней за 30</dt><dd>{user.active_days_30}</dd></div>
            <div><dt>Платформа</dt><dd>{platformLabel(user.last_platform)}</dd></div>
            <div><dt>Уведомления</dt><dd>{card.data.push_enabled ? 'включены' : 'выключены'}</dd></div>
          </dl>
          <div className="product-count-groups">
            {COUNT_GROUPS.map((group) => (
              <div key={group.title}>
                <h3 className="product-subtitle">{group.title}</h3>
                <ul>
                  {group.events.map((name) => (
                    <li key={name}><span>{eventLabel(name)}</span><b>{card.data.counts[name] ?? 0}</b></li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="product-section" aria-labelledby="user-events">
        <h2 id="user-events">Действия</h2>
        {events.data && items.length === 0 && <p className="muted">Событий пока нет: пользователь не заходил после включения статистики.</p>}
        {items.length > 0 && (
          <div className="import-table-scroll">
            <table className="import-table product-table">
              <thead><tr><th>Когда</th><th>Что</th><th>Подробности</th><th>Платформа</th><th>Версия</th></tr></thead>
              <tbody>
                {items.map((event) => (
                  <tr key={event.id}>
                    <td>{formatDateTime(event.occurred_at)}</td>
                    <td>{eventLabel(event.name)}</td>
                    <td>{event.detail ? `«${event.detail}»` : '—'}</td>
                    <td>{platformLabel(event.platform)}</td>
                    <td>{event.app_version ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {events.hasNextPage && (
          <button className="button button-secondary" onClick={() => events.fetchNextPage()} disabled={events.isFetchingNextPage}>
            {events.isFetchingNextPage ? 'Загружаем…' : 'Показать раньше'}
          </button>
        )}
      </section>
    </>
  )
}
