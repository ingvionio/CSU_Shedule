/**
 * Типы контракта бэкенд -> фронтенд (03-schedule-json.md).
 *
 * Расписание приходит готовым: чётность, сроки действия и сортировка
 * уже применены на бэкенде. Фронт только отображает.
 */

export type WeekParity = 'odd' | 'even'

/** Статус пары. Список может пополняться — незнакомый код не должен ломать экран. */
export type LessonStatus = 'regular' | 'changed' | 'cancelled' | 'moved_out' | 'moved_in' | 'added'

export type Group = {
  id: number
  name: string
  course: number
}

export type TimeSlot = {
  number: number
  start_time: string
  end_time: string
}

export type LessonType = {
  code: string
  /** Показывать нужно именно `name`: коды форматов будут добавляться. */
  name: string
}

export type LessonChange = {
  kind: 'cancel' | 'replace' | 'move' | 'add'
  comment: string | null
  original: Record<string, unknown> | null
  moved_to: { date: string; slot: number | null; start_time: string; end_time: string } | null
  moved_from: { date: string; slot: number | null; start_time: string; end_time: string } | null
}

export type Lesson = {
  id: string
  /** HH:MM, заполнено всегда. */
  start_time: string
  end_time: string
  /** Номер пары в сетке звонков; null — пара вне сетки (например, в 19:00). */
  slot: number | null
  subject: string
  type: LessonType
  room: string | null
  teacher: string | null
  /** Подгруппа из Excel; null — пара всей группы. */
  subgroup: number | null
  status: LessonStatus
  change: LessonChange | null
}

export type Day = {
  /** YYYY-MM-DD */
  date: string
  /** 1 = пн ... 6 = сб */
  weekday: number
  is_today: boolean
  /** Уже отсортированы по времени начала. */
  lessons: Lesson[]
}

export type Week = {
  number: number
  parity: WeekParity
  start_date: string
  end_date: string
  is_current: boolean
  prev: number | null
  next: number | null
}

export type WeekSchedule = {
  group: Group
  week: Week
  generated_at: string
  days: Day[]
}

export type CurrentWeek = {
  number: number
  parity: WeekParity
  start_date: string
  end_date: string
  semester: { id: number; title: string; total_weeks: number }
}
