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
  /** Направление (поток): «ПИ», «ПрИ», «БИ». null — не распознано по названию. */
  direction: string | null
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

export type OverrideKind = 'cancel' | 'replace' | 'move' | 'add'

export type MovePoint = { date: string; slot: number | null; start_time: string; end_time: string }

export type LessonChange = {
  /** id изменения на бэкенде — по нему админ откатывает изменение. */
  override_id: number
  kind: OverrideKind
  comment: string | null
  original: Record<string, unknown> | null
  moved_to: MovePoint | null
  moved_from: MovePoint | null
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

/* --- Админка --- */

export type AdminSession = {
  token: string
  /** ISO datetime истечения токена. */
  expires_at: string
}

export type TokenResponse = {
  access_token: string
  token_type: 'bearer'
  expires_at: string
}

/**
 * Временное изменение для группы или потока (POST /admin/overrides).
 * Поля итоговой пары: не передано или совпадает с исходной — без изменений.
 * Пустая строка в teacher / room — убрать значение.
 */
export type OverrideInput = {
  group_ids: number[]
  kind: OverrideKind
  date: string
  source_lesson_id?: number | null
  target_date?: string | null
  slot?: number | null
  start_time?: string | null
  end_time?: string | null
  subject?: string | null
  lesson_type?: string | null
  teacher?: string | null
  room?: string | null
  comment?: string | null
}

export type OverrideCreated = {
  batch_id: string
  override_ids: number[]
  group_ids: number[]
}

export type Catalog = {
  subjects: string[]
  teachers: string[]
  rooms: string[]
}

/* --- Обращения --- */

/** Кому адресовано обращение. `unknown` — студент не знает, админ распределит. */
export type FeedbackKind = 'dev' | 'methodist' | 'deanery' | 'unknown'
export type FeedbackStatus = 'new' | 'in_progress' | 'answered' | 'archived'

export type FeedbackInput = {
  kind: FeedbackKind
  text: string
  group_id?: number | null
  author_name?: string | null
  contact?: string | null
  /** Ловушка для ботов, человек оставляет пустым. */
  website?: string
}

export type FeedbackReply = {
  id: number
  author_kind: 'staff' | 'student'
  /** От кого: «Деканат», «Методист», «Вы». */
  author_title: string
  text: string
  created_at: string
}

export type MyFeedback = {
  id: number
  kind: FeedbackKind
  kind_title: string
  text: string
  status: FeedbackStatus
  created_at: string
  replies: FeedbackReply[]
}

export type AdminFeedback = Omit<MyFeedback, 'replies'> & {
  recipient_title: string | null
  group_id: number | null
  group_name: string | null
  author_name: string | null
  contact: string | null
  contact_is_email: boolean
  admin_note: string | null
  replies: (FeedbackReply & { author_name: string | null })[]
}

export type FeedbackFolder = {
  kind: FeedbackKind
  title: string
  total: number
  new: number
}

export type FeedbackUpdate = {
  status?: FeedbackStatus
  kind?: FeedbackKind
  admin_note?: string
}

export type FeedbackRecipient = {
  id: number
  kind: Exclude<FeedbackKind, 'unknown'>
  title: string
  emails: string[]
  is_active: boolean
}

export type RecipientUpdate = Partial<Pick<FeedbackRecipient, 'title' | 'emails' | 'is_active'>>

/* --- Профиль студента и рассылка --- */

export type Direction = {
  code: string
  /** Курсы, на которых есть группы этого направления. */
  courses: number[]
}

export type StudentProfile = {
  id: number
  /** Персональные данные: собираем только ФИО и группу. */
  full_name: string
  group_id: number | null
  group_name: string | null
}

export type StudentSession = {
  token: string
  expires_at: string
  profile: StudentProfile
}

export type StudentTokenResponse = TokenResponse & { profile: StudentProfile }

export type Importance = 'low' | 'normal' | 'high'

export type InboxMessage = {
  id: number
  title: string
  body: string
  importance: Importance
  sent_at: string
  read_at: string | null
  acknowledged_at: string | null
  /** Важное сообщение: нужно нажать «Ознакомлен». */
  requires_ack: boolean
  /** Не прочитано, а у важных — не подтверждено. */
  is_unread: boolean
}

export type Inbox = {
  unread_count: number
  messages: InboxMessage[]
}

export type MessageTargetType = 'all' | 'course' | 'direction' | 'group' | 'students'

export type MessageTarget = {
  type: MessageTargetType
  courses?: number[]
  directions?: string[]
  group_ids?: number[]
  user_ids?: number[]
}

export type MessageInput = {
  title: string
  body: string
  importance: Importance
  target: MessageTarget
}

export type AdminMessage = {
  id: number
  title: string
  body: string
  importance: Importance
  target: MessageTarget
  /** Адресация словами: «Курс 1», «Поток ПИ». */
  target_title: string
  created_by: string | null
  sent_at: string
  last_reminded_at: string | null
  recipients_total: number
  read_count: number
  acknowledged_count: number
}

export type RecipientStatus = {
  user_id: number
  full_name: string
  group_name: string | null
  read_at: string | null
  acknowledged_at: string | null
  reminded_at: string | null
}

export type AdminMessageDetail = AdminMessage & { recipients: RecipientStatus[] }

export type Student = {
  id: number
  full_name: string
  group_id: number | null
  group_name: string | null
  course: number | null
}
