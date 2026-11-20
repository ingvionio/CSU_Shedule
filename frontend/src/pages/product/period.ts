/** Период ЛК продукта: пресеты и произвольные даты. Даты — `YYYY-MM-DD` по Челябинску. */

export type Period = { start: string; end: string; preset: PresetId }
export type PresetId = 'today' | 'week' | 'month' | 'quarter' | 'year' | 'custom'

export const PRESETS: { id: Exclude<PresetId, 'custom'>; label: string; days: number }[] = [
  { id: 'today', label: 'Сегодня', days: 1 },
  { id: 'week', label: 'Последние 7 дней', days: 7 },
  { id: 'month', label: 'Последние 30 дней', days: 30 },
  { id: 'quarter', label: 'Последние 90 дней', days: 90 },
  { id: 'year', label: 'Последние 12 месяцев', days: 365 },
]

export const MAX_DAYS = 731

const LOCAL_DATE = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Yekaterinburg', year: 'numeric', month: '2-digit', day: '2-digit',
})

/** Сегодня по Челябинску, независимо от пояса браузера. */
export function todayLocal(now = new Date()): string {
  return LOCAL_DATE.format(now)
}

export function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

export function daysBetween(start: string, end: string): number {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1
}

export function presetPeriod(id: Exclude<PresetId, 'custom'>, today = todayLocal()): Period {
  const preset = PRESETS.find((item) => item.id === id)!
  return { start: addDays(today, 1 - preset.days), end: today, preset: id }
}

/** Ошибка произвольного периода или null, если он корректен. */
export function periodError(start: string, end: string): string | null {
  if (!start || !end) return 'Укажите обе даты'
  if (start > end) return 'Начало позже конца'
  if (daysBetween(start, end) > MAX_DAYS) return `Не больше ${MAX_DAYS} дней`
  return null
}

/** Предыдущий период той же длины — для сравнения. */
export function previousPeriod(period: { start: string; end: string }): { start: string; end: string } {
  const days = daysBetween(period.start, period.end)
  return { start: addDays(period.start, -days), end: addDays(period.start, -1) }
}
