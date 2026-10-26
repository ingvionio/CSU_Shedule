import type {
  AdminFeedback,
  Catalog,
  CurrentWeek,
  FeedbackFolder,
  FeedbackInput,
  FeedbackRecipient,
  FeedbackUpdate,
  Group,
  MyFeedback,
  RecipientUpdate,
  LessonType,
  OverrideCreated,
  OverrideInput,
  TimeSlot,
  TokenResponse,
  WeekSchedule,
} from './types'

const BASE_URL = (import.meta.env.VITE_API_URL ?? '') + '/api/v1'

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  /** JWT администратора для эндпоинтов /admin. */
  token?: string
  /** Токен устройства для обращений студента. */
  feedbackToken?: string
}

async function request<T>(path: string, { method = 'GET', body, token, feedbackToken }: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`
  if (feedbackToken) headers['X-Feedback-Token'] = feedbackToken

  let response: Response
  try {
    response = await fetch(BASE_URL + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('Нет связи с сервером расписания', 0)
  }

  if (!response.ok) {
    // Бэкенд присылает причину в detail, её можно показать как есть.
    // У ошибок валидации (422 от FastAPI) detail — список, берём первое сообщение.
    const payload = await response.json().catch(() => null)
    const detail = Array.isArray(payload?.detail) ? payload.detail[0]?.msg : payload?.detail
    throw new ApiError(detail ?? `Ошибка запроса (${response.status})`, response.status)
  }

  return response.json() as Promise<T>
}

export const api = {
  groups: () => request<Group[]>('/groups'),
  timeSlots: () => request<TimeSlot[]>('/time-slots'),
  lessonTypes: () => request<LessonType[]>('/lesson-types'),
  currentWeek: () => request<CurrentWeek>('/weeks/current'),
  schedule: (groupId: number, week?: number) =>
    request<WeekSchedule>(`/groups/${groupId}/schedule${week ? `?week=${week}` : ''}`),

  adminLogin: (login: string, password: string) =>
    request<TokenResponse>('/auth/admin/login', { method: 'POST', body: { login, password } }),
  catalog: (token: string) => request<Catalog>('/admin/catalog', { token }),
  createOverride: (token: string, body: OverrideInput) =>
    request<OverrideCreated>('/admin/overrides', { method: 'POST', body, token }),
  deleteOverride: (token: string, id: number, batch: boolean) =>
    request<{ deleted: number }>(`/admin/overrides/${id}${batch ? '?batch=true' : ''}`, { method: 'DELETE', token }),

  sendFeedback: (feedbackToken: string, body: FeedbackInput) =>
    request<{ id: number; kind_title: string }>('/feedback', { method: 'POST', body, feedbackToken }),
  myFeedback: (feedbackToken: string) => request<MyFeedback[]>('/feedback/mine', { feedbackToken }),

  feedbackFolders: (token: string) => request<FeedbackFolder[]>('/admin/feedback/folders', { token }),
  adminFeedback: (token: string, kind: string, status: string) => {
    const params = new URLSearchParams({ kind, ...(status ? { status } : {}) })
    return request<AdminFeedback[]>(`/admin/feedback?${params}`, { token })
  },
  updateFeedback: (token: string, id: number, body: FeedbackUpdate) =>
    request<AdminFeedback>(`/admin/feedback/${id}`, { method: 'PATCH', body, token }),
  replyFeedback: (token: string, id: number, text: string) =>
    request<AdminFeedback>(`/admin/feedback/${id}/replies`, { method: 'POST', body: { text }, token }),
  feedbackRecipients: (token: string) => request<FeedbackRecipient[]>('/admin/feedback/recipients', { token }),
  updateRecipient: (token: string, id: number, body: RecipientUpdate) =>
    request<FeedbackRecipient>(`/admin/feedback/recipients/${id}`, { method: 'PATCH', body, token }),
}
