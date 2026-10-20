import type { CurrentWeek, Group, TimeSlot, WeekSchedule } from './types'

const BASE_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000') + '/api/v1'

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

async function request<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE_URL + path)
  } catch {
    throw new ApiError('Нет связи с сервером расписания', 0)
  }

  if (!response.ok) {
    // Бэкенд присылает причину в detail, её можно показать как есть.
    const detail = await response.json().catch(() => null)
    throw new ApiError(detail?.detail ?? `Ошибка запроса (${response.status})`, response.status)
  }

  return response.json() as Promise<T>
}

export const api = {
  groups: () => request<Group[]>('/groups'),
  timeSlots: () => request<TimeSlot[]>('/time-slots'),
  currentWeek: () => request<CurrentWeek>('/weeks/current'),
  schedule: (groupId: number, week?: number) =>
    request<WeekSchedule>(`/groups/${groupId}/schedule${week ? `?week=${week}` : ''}`),
}
