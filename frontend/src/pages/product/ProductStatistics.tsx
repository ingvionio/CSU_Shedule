import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { LogIn, LogOut, RefreshCw, Search, X } from 'lucide-react'

import { clearProductSession, readProductSession, writeProductSession } from '../../api/cache'
import { ApiError, api } from '../../api/client'
import type { AdminSession, ProductPeriod, ProductSummary, ProductUser } from '../../api/types'
import { conversion, eventLabel, formatDateTime, formatDay, platformLabel } from './labels'

const PERIODS: { value: ProductPeriod; label: string }[] = [
  { value: 1, label: 'Сегодня' },
  { value: 7, label: '7 дней' },
  { value: 30, label: '30 дней' },
  { value: 90, label: '90 дней' },
]
const PAGE = 50

/** ЛК продукта: статистика для разработчиков и менеджера продукта. Открывается по /statistic. */
export function ProductStatistics() {
  const [session, setSession] = useState<AdminSession | null>(() => readProductSession())

  const login = (next: AdminSession) => {
    writeProductSession(next)
    setSession(next)
  }
  const logout = () => {
    clearProductSession()
    setSession(null)
  }

  return (
    <main className="product-page">
      {session ? <Dashboard token={session.token} onLogout={logout} /> : <ProductLogin onLogin={login} />}
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
      <input
        id="product-password"
        className="text-field"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
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

function Dashboard({ token, onLogout }: { token: string; onLogout: () => void }) {
  const [days, setDays] = useState<ProductPeriod>(30)
  const [selected, setSelected] = useState<ProductUser | null>(null)
  const summary = useQuery({
    queryKey: ['product-summary', days, token],
    queryFn: () => api.productSummary(token, days),
    staleTime: 60 * 1000,
  })
  useSessionGuard(summary.error, onLogout)

  return (
    <div className="product-dashboard">
      <header className="product-header">
        <div>
          <div className="eyebrow">ЛК ПРОДУКТА · РАСПИСАНИЕ ИИТ</div>
          <h1>Статистика</h1>
          {summary.data && (
            <p className="muted">
              {formatDay(summary.data.start_date)} — {formatDay(summary.data.end_date)}, время по Челябинску
            </p>
          )}
        </div>
        <div className="product-header-actions">
          <button className="button button-secondary" onClick={() => summary.refetch()} disabled={summary.isFetching}>
            <RefreshCw size={16} />Обновить
          </button>
          <button className="button button-secondary" onClick={onLogout}><LogOut size={16} />Выйти</button>
        </div>
      </header>

      <div className="admin-target-tabs product-periods" role="tablist" aria-label="Период">
        {PERIODS.map((period) => (
          <button key={period.value} role="tab" aria-selected={days === period.value} className={days === period.value ? 'active' : ''} onClick={() => setDays(period.value)}>
            {period.label}
          </button>
        ))}
      </div>

      {summary.isLoading && <div className="state-note">Считаем статистику…</div>}
      {summary.isError && !(summary.error instanceof ApiError && summary.error.status === 401) && (
        <div className="state-note error-note">{(summary.error as Error).message}</div>
      )}
      {summary.data && <SummaryView data={summary.data} />}

      {selected && <UserEvents key={selected.id} token={token} user={selected} onClose={() => setSelected(null)} onLogout={onLogout} />}
      <UsersSection token={token} onLogout={onLogout} onSelect={setSelected} />
    </div>
  )
}

function Tile({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="product-tile">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )
}

function SummaryView({ data }: { data: ProductSummary }) {
  const steps = [
    ['Открыли лендинг', data.funnel.landing_view],
    ['Нажали «Войти через Moodle»', data.funnel.login_click],
    ['Отправили форму', data.funnel.login_submit],
    ['Вошли', data.funnel.login_success],
  ] as const
  const failures = data.login_failures.auth + data.login_failures.group + data.login_failures.other
  const platforms = Object.entries(data.by_platform).sort((a, b) => b[1] - a[1])

  return (
    <>
      <section className="product-section" aria-labelledby="product-users-title">
        <h2 id="product-users-title">Пользователи</h2>
        <div className="product-tiles">
          <Tile label="Всего пользователей" value={data.users_total} hint="студентов с профилем" />
          <Tile label="Новые за период" value={data.users_new} />
          <Tile label="DAU" value={data.dau} hint="за сегодня" />
          <Tile label="WAU" value={data.wau} hint="за 7 дней" />
          <Tile label="MAU" value={data.mau} hint="за 30 дней" />
        </div>
        {platforms.length > 0 && (
          <p className="muted product-platforms">
            Активные за период по платформе: {platforms.map(([platform, count]) => `${platformLabel(platform)} — ${count}`).join(', ')}
          </p>
        )}
      </section>

      <section className="product-section" aria-labelledby="product-funnel-title">
        <h2 id="product-funnel-title">Воронка входа</h2>
        <p className="muted">Уникальные устройства за период. Процент — переход с предыдущего шага.</p>
        <ol className="product-funnel">
          {steps.map(([label, value], index) => (
            <li key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
              {index > 0 && <small>{conversion(value, steps[index - 1][1])}</small>}
            </li>
          ))}
        </ol>
        <p className="muted">
          Неудачных входов: {failures}
          {failures > 0 && ` — неверный логин или пароль ${data.login_failures.auth}, группа не определилась ${data.login_failures.group}, Moodle недоступен или ошибка ${data.login_failures.other}`}
        </p>
      </section>

      <section className="product-section" aria-labelledby="product-apk-title">
        <h2 id="product-apk-title">Android</h2>
        <div className="product-tiles">
          <Tile label="Скачиваний APK" value={data.apk_downloads} hint="открытий страницы /download" />
          <Tile label="Установок за период" value={data.apk_installs} hint="первый запуск APK" />
          <Tile label="Установок всего" value={data.apk_installs_total} />
        </div>
      </section>

      <section className="product-section" aria-labelledby="product-daily-title">
        <h2 id="product-daily-title">По дням</h2>
        <div className="import-table-scroll">
          <table className="import-table product-table">
            <thead>
              <tr><th>День</th><th>DAU</th><th>Новые</th><th>Лендинг</th><th>Входы</th></tr>
            </thead>
            <tbody>
              {[...data.daily].reverse().map((day) => (
                <tr key={day.date}>
                  <td>{formatDay(day.date)}</td>
                  <td>{day.dau}</td>
                  <td>{day.new_users}</td>
                  <td>{day.landing_devices}</td>
                  <td>{day.login_success}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

function UsersSection({ token, onLogout, onSelect }: { token: string; onLogout: () => void; onSelect: (user: ProductUser) => void }) {
  const [input, setInput] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<'last_seen' | 'created'>('last_seen')
  const [offset, setOffset] = useState(0)
  const users = useQuery({
    queryKey: ['product-users', q, sort, offset, token],
    queryFn: () => api.productUsers(token, { q, sort, limit: PAGE, offset }),
    placeholderData: (previous) => previous,
  })
  useSessionGuard(users.error, onLogout)

  const search = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setQ(input)
  }
  const total = users.data?.total ?? 0

  return (
    <section className="product-section" aria-labelledby="product-list-title">
      <h2 id="product-list-title">Кто заходил</h2>
      <form className="product-search" onSubmit={search}>
        <input className="text-field" placeholder="Поиск по ФИО" value={input} onChange={(event) => setInput(event.target.value)} aria-label="Поиск по ФИО" />
        <button className="button button-secondary"><Search size={16} />Найти</button>
        <select
          className="select-field"
          value={sort}
          onChange={(event) => { setSort(event.target.value as 'last_seen' | 'created'); setOffset(0) }}
          aria-label="Сортировка"
        >
          <option value="last_seen">Сначала недавно заходившие</option>
          <option value="created">Сначала новые</option>
        </select>
      </form>
      {users.isError && !(users.error instanceof ApiError && users.error.status === 401) && (
        <div className="state-note error-note">{(users.error as Error).message}</div>
      )}
      {users.data && (
        <>
          <div className="import-table-scroll">
            <table className="import-table product-table">
              <thead>
                <tr><th>Студент</th><th>Группа</th><th>Последний заход</th><th>Дней за 30</th><th>Платформа</th><th>Профиль создан</th></tr>
              </thead>
              <tbody>
                {users.data.items.map((user) => (
                  <tr key={user.id}>
                    <td><button className="product-user-link" onClick={() => onSelect(user)}>{user.full_name}</button></td>
                    <td>{user.group ? `${user.group.name} · ${user.group.course} курс` : '—'}</td>
                    <td>{formatDateTime(user.last_seen_at)}</td>
                    <td>{user.active_days_30}</td>
                    <td>{platformLabel(user.last_platform)}</td>
                    <td>{formatDateTime(user.created_at)}</td>
                  </tr>
                ))}
                {users.data.items.length === 0 && <tr><td colSpan={6}>Никого не нашли</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="product-pager">
            <span className="muted">{total === 0 ? '0' : `${offset + 1}–${Math.min(offset + PAGE, total)}`} из {total}</span>
            <button className="button button-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(offset - PAGE, 0))}>Назад</button>
            <button className="button button-secondary" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Дальше</button>
          </div>
        </>
      )}
    </section>
  )
}

function UserEvents({ token, user, onClose, onLogout }: { token: string; user: ProductUser; onClose: () => void; onLogout: () => void }) {
  const events = useInfiniteQuery({
    queryKey: ['product-user-events', user.id, token],
    queryFn: ({ pageParam }) => api.productUserEvents(token, user.id, pageParam),
    initialPageParam: null as number | null,
    getNextPageParam: (page) => page.next_before,
  })
  useSessionGuard(events.error, onLogout)
  const items = events.data?.pages.flatMap((page) => page.items) ?? []
  const panel = useRef<HTMLElement>(null)
  useEffect(() => {
    panel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  return (
    <section ref={panel} className="product-section product-user-events" aria-labelledby="product-user-title">
      <div className="product-user-heading">
        <div>
          <h2 id="product-user-title">{user.full_name}</h2>
          <p className="muted">
            {user.group ? `${user.group.name}, ${user.group.course} курс` : 'Группа не указана'} · профиль создан {formatDateTime(user.created_at)}
          </p>
        </div>
        <button className="button button-secondary" onClick={onClose} aria-label="Закрыть"><X size={16} /></button>
      </div>
      {events.isLoading && <div className="state-note">Загружаем события…</div>}
      {events.isError && !(events.error instanceof ApiError && events.error.status === 401) && (
        <div className="state-note error-note">{(events.error as Error).message}</div>
      )}
      {events.data && items.length === 0 && <p className="muted">Событий пока нет: пользователь не заходил после включения статистики.</p>}
      {items.length > 0 && (
        <div className="import-table-scroll">
          <table className="import-table product-table">
            <thead><tr><th>Когда</th><th>Что</th><th>Платформа</th><th>Версия</th></tr></thead>
            <tbody>
              {items.map((event) => (
                <tr key={event.id}>
                  <td>{formatDateTime(event.occurred_at)}</td>
                  <td>{eventLabel(event.name)}</td>
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
  )
}
