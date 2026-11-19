/** Подписи ЛК продукта. Неизвестное имя события показывается как есть. */

export const EVENT_LABELS: Record<string, string> = {
  landing_view: 'Открыл лендинг',
  login_click: 'Нажал «Войти через Moodle»',
  login_submit: 'Отправил форму входа',
  login_success: 'Вошёл через Moodle',
  login_failed_auth: 'Неудачный вход: неверный логин или пароль',
  login_failed_group: 'Неудачный вход: группа не определилась',
  login_failed_other: 'Неудачный вход: Moodle недоступен или ошибка',
  app_open: 'Открыл приложение',
  apk_download: 'Скачал APK',
}

export const PLATFORM_LABELS: Record<string, string> = {
  web: 'Браузер',
  pwa: 'PWA (на экране «Домой»)',
  apk: 'Android APK',
  unknown: 'Не определена',
}

export function eventLabel(name: string): string {
  return EVENT_LABELS[name] ?? name
}

export function platformLabel(platform: string | null | undefined): string {
  return platform ? PLATFORM_LABELS[platform] ?? platform : '—'
}

const DATE_TIME = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Asia/Yekaterinburg',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})
const DATE = new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC', day: '2-digit', month: '2-digit', weekday: 'short' })

/** Время события по Челябинску. */
export function formatDateTime(value: string | null): string {
  return value ? DATE_TIME.format(new Date(value)) : '—'
}

/** Календарная дата `YYYY-MM-DD` (уже по Челябинску с сервера). */
export function formatDay(value: string): string {
  return DATE.format(new Date(`${value}T00:00:00Z`))
}

/** Доля следующего шага воронки от предыдущего. */
export function conversion(current: number, previous: number): string {
  if (previous <= 0) return '—'
  return `${Math.round((current / previous) * 100)}%`
}
