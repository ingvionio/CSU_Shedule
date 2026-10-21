import type {
  Catalog,
  CurrentWeek,
  Group,
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
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  /** JWT администратора для эндпоинтов /admin. */
  token?: string
}

async function request<T>(path: string, { method = 'GET', body, token }: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`

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
}
