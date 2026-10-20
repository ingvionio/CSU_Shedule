import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { readCache, writeCache } from './cache'
import type { CurrentWeek, Group, TimeSlot, WeekSchedule } from './types'

export function useGroups(): UseQueryResult<Group[]> {
  return useQuery({
    queryKey: ['groups'],
    queryFn: async () => writeCache('groups', await api.groups()),
    initialData: () => readCache<Group[]>('groups') ?? undefined,
    staleTime: 60 * 60 * 1000,
  })
}

export function useTimeSlots(): UseQueryResult<TimeSlot[]> {
  return useQuery({
    queryKey: ['time-slots'],
    queryFn: async () => writeCache('time-slots', await api.timeSlots()),
    initialData: () => readCache<TimeSlot[]>('time-slots') ?? undefined,
    staleTime: 24 * 60 * 60 * 1000,
  })
}

export function useCurrentWeek(): UseQueryResult<CurrentWeek> {
  return useQuery({
    queryKey: ['current-week'],
    queryFn: async () => writeCache('current-week', await api.currentWeek()),
    initialData: () => readCache<CurrentWeek>('current-week') ?? undefined,
    staleTime: 60 * 60 * 1000,
  })
}

/**
 * Расписание группы на неделю.
 *
 * Последний успешный ответ сохраняется на устройстве, поэтому расписание
 * открывается и без сети; при появлении связи данные обновляются.
 */
export function useSchedule(groupId: number | null, week: number | null): UseQueryResult<WeekSchedule> {
  const key = groupId !== null && week !== null ? `schedule-${groupId}-${week}` : null

  return useQuery({
    queryKey: ['schedule', groupId, week],
    queryFn: async () => writeCache(key!, await api.schedule(groupId!, week!)),
    initialData: () => (key ? readCache<WeekSchedule>(key) ?? undefined : undefined),
    enabled: groupId !== null && week !== null,
    staleTime: 5 * 60 * 1000,
  })
}
