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
  schedule_day_view: 'Смотрел расписание на день',
  schedule_week_view: 'Смотрел расписание на неделю',
  note_saved: 'Сохранил заметку к паре',
  map_open: 'Открыл карту',
  help_open: 'Открыл справку',
  message_received: 'Получил сообщение',
  push_sent: 'Получил push-уведомление',
  push_open: 'Открыл приложение из уведомления',
  message_read: 'Прочитал сообщение',
  message_ack: 'Нажал «Ознакомлен»',
  feedback_sent: 'Написал вопрос',
  push_subscribed: 'Включил уведомления',
}

/** Короткие названия функций для графика использования. */
export const FEATURE_LABELS: Record<string, string> = {
  app_open: 'Заходы в приложение',
  schedule_day_view: 'Расписание на день',
  schedule_week_view: 'Расписание на неделю',
  note_saved: 'Заметки к парам',
  map_open: 'Карта',
  help_open: 'Справка',
  message_received: 'Получено сообщений',
  push_sent: 'Доставлено push',
  push_open: 'Открыто из push',
  message_read: 'Прочитано сообщений',
  message_ack: '«Ознакомлен»',
  feedback_sent: 'Вопросы',
  push_subscribed: 'Включили уведомления',
}

/** Группы счётчиков в карточке пользователя. */
export const COUNT_GROUPS: { title: string; events: string[] }[] = [
  { title: 'Заходы', events: ['login_success', 'app_open'] },
  { title: 'Расписание', events: ['schedule_day_view', 'schedule_week_view', 'note_saved'] },
  { title: 'Сообщения и уведомления', events: ['message_received', 'push_sent', 'push_open', 'message_read', 'message_ack'] },
  { title: 'Другое', events: ['feedback_sent', 'map_open', 'help_open', 'push_subscribed'] },
]

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
const DATE = new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC', day: 'numeric', month: 'long', year: 'numeric' })

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

export function percent(part: number, whole: number): string {
  return whole > 0 ? `${Math.round((part / whole) * 100)}%` : '—'
}
