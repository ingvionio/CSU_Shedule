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
  level: 'bachelor' | 'master'
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

export type ScheduleEvent = { kind: ExamKind; note: string | null; groups: string[] }
export type EventChange = { original: Partial<Record<ExamChangedField, string | null>> }

export type Lesson = {
  id: string
  note_key?: string | null
  stream_diff?: string[] | null
  /** HH:MM; null — время события не указано. */
  start_time: string | null
  end_time: string | null
  /** Номер пары в сетке звонков; null — пара вне сетки (например, в 19:00). */
  slot: number | null
  subject: string
  type: LessonType
  room: string | null
  online_url: string | null
  teacher: string | null
  /** Подгруппа из Excel; null — пара всей группы. */
  subgroup: number | null
  status: LessonStatus
  change: LessonChange | EventChange | null
  event: ScheduleEvent | null
}

export type Day = {
  /** YYYY-MM-DD */
  date: string
  /** 1 = пн ... 7 = вс */
  weekday: number
  is_today: boolean
  /** Уже отсортированы по времени начала. */
  lessons: Lesson[]
}

export type Week = {
  schedule_pending: boolean
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
  moodle_username?: string | null
  moodle_auth_error?: boolean
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
  push: { configured: boolean; total: number; sent: number; pending: number; failed: number }
}

export type RemindOut = { reminded: number; devices: number; push_configured: boolean }

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

export type HomeworkSource = 'from_class' | 'moodle' | 'chat' | 'unknown'
export type HomeworkStatus = 'published' | 'completed' | 'archived'

export type GroupHomework = {
  id: number
  group_id: number
  group_name: string
  lesson_id: number | null
  lesson_date: string | null
  subject: string | null
  title: string
  body: string
  due_date: string | null
  source: HomeworkSource
  status: HomeworkStatus
  version: number
  created_by: number
  created_by_name: string
  updated_by: number
  updated_by_name: string
  created_at: string
  updated_at: string
  completed_by_me: boolean
}

export type HomeworkList = { can_edit: boolean; items: GroupHomework[] }

export type HomeworkInput = {
  title: string
  body: string
  lesson_date?: string | null
  lesson_id?: number | null
  subject?: string | null
  due_date?: string | null
  source: HomeworkSource
}

export type HomeworkPatch = Partial<HomeworkInput> & { version: number; status?: HomeworkStatus }

export type GroupEditor = { user_id: number; full_name: string; group_id: number; is_primary: boolean; active: boolean }

export type PersonalNote = {
  id: number
  occurrence_key: string
  group_id: number
  lesson_date: string
  subject: string
  body: string
  version: number
  updated_at: string
}

export type NoteInput = { group_id: number; lesson_date: string; lesson_ref: string; body: string; version: number }

export type ImportIssue = { sheet: string; cell: string; text: string; reason: string }

export type WeeklyImportReport = {
  files: {
    file_name: string
    group_name: string | null
    week_number: number | null
    parity: WeekParity | null
    start_date: string | null
    end_date: string | null
    lessons_count: number
    errors: ImportIssue[]
    warnings: ImportIssue[]
  }[]
  files_count: number
  groups_count: number
  groups_created: number
  lessons_created: number
  overrides_deleted: number
  homework_rebound: number
  homework_unbound: number
  errors_count: number
  warnings_count: number
  applied: boolean
  import_id: number | null
}

export type SemesterImportReport = {
  file_name: string
  groups: { name: string; lessons_count: number }[]
  errors: ImportIssue[]
  warnings: ImportIssue[]
  lessons_replaced: number
  overrides_deleted: number
  homework_affected: number
  homework_rebound: number
  homework_unbound: number
  groups_created: number
  lessons_created: number
  semester_title: string
  applied: boolean
  import_id: number | null
}

export type ImportHistory = {
  id: number
  file_name: string
  uploaded_at: string
  uploaded_by: string | null
  status: string
  lessons_count: number
  errors_count: number
  warnings_count: number
}

/* Сессия и пересдачи */
export type ExamKind = 'session' | 'retake'
export type ExamType = 'consultation' | 'exam' | 'credit' | 'graded_credit' | 'other'
export type ExamChangedField = 'date' | 'start_time' | 'room'
export type ExamGroup = { id: number; name: string; course: number }
export type ExamValues = {
  kind: ExamKind; date: string; start_time: string | null; subject: string
  teacher: string | null; room: string | null; note: string | null
  event_type: ExamType | null
}
export type ExamInput = ExamValues & { group_ids: number[] }
export type ExamOriginal = Partial<Record<ExamChangedField, string | null>> | null
export type ExamEvent = ExamValues & {
  original: ExamOriginal
  id: number; semester_id: number; groups: ExamGroup[]; cancelled: boolean
  source: 'import' | 'manual'; import_id: number | null; created_at: string; updated_at: string
}
export type ExamWarning = { sheet: string; row: number; column: string; text: string; reason: string }
export type ExamMapping = { short_name: string; group_id: number | null; group_name: string | null }
export type ExamPreview = ExamValues & { sheet: string; row: number; groups: ExamGroup[]; original: ExamOriginal }
export type ExamImportReport = {
  events_count: number; warnings: ExamWarning[]; mappings: ExamMapping[]; rows: ExamPreview[]
  sheets: { sheet: string; groups: string[]; academic_year: string | null; events_count: number }[]
  applied: boolean; import_id: number | null
}
export type ExamImportHistory = {
  id: number; semester_id: number; kind: ExamKind; file_name: string; events_count: number
  warnings: ExamWarning[]; uploaded_by: string | null; uploaded_at: string
}
/* --- ЛК продукта (/statistic) --- */

export type ProductSummary = {
  start_date: string
  end_date: string
  days: number
  users_total: number
  users_new: number
  active_users: number
  dau: number
  wau: number
  mau: number
  users_with_push: number
  funnel: {
    landing_view: number; login_click: number; login_submit: number; login_success: number
    login_any: number; login_without_landing: number
  }
  tracking_since: string | null
  login_failures: { auth: number; group: number; other: number }
  apk_downloads: number
  apk_installs: number
  apk_installs_total: number
  by_platform: Record<string, number>
  features: { name: string; events: number; users: number }[]
  retention: { week: number; eligible: number; returned: number }[]
  groups: { id: number; name: string; course: number; level: 'bachelor' | 'master'; users: number; new: number; active: number }[]
  daily: { date: string; dau: number; new_users: number; landing_devices: number; login_success: number }[]
}

export type ProductUser = {
  id: number
  full_name: string
  group: { id: number; name: string; course: number } | null
  created_at: string
  last_seen_at: string | null
  active_days_30: number
  last_platform: string | null
}

export type ProductUsers = { total: number; items: ProductUser[] }

export type ProductUserFilters = {
  q?: string
  group_id?: number | null
  last_seen_from?: string
  last_seen_to?: string
  created_from?: string
  created_to?: string
  platform?: 'web' | 'pwa' | 'apk' | 'unknown' | null
  sort: 'last_seen' | 'created' | 'name' | 'group' | 'active_days' | 'platform'
  order: 'asc' | 'desc'
  limit: number
  offset: number
}

export type ProductUserDetail = { user: ProductUser; counts: Record<string, number>; push_enabled: boolean }

export type ProductEvent = {
  id: number
  occurred_at: string
  name: string
  platform: string | null
  app_version: string | null
  detail: string | null
}

export type ProductUserEvents = { items: ProductEvent[]; next_before: number | null }
