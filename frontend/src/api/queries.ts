import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { feedbackToken, readCache, writeCache } from './cache'
import type {
  Catalog,
  CurrentWeek,
  FeedbackInput,
  FeedbackUpdate,
  Group,
  LessonType,
  OverrideInput,
  RecipientUpdate,
  TimeSlot,
  WeekSchedule,
} from './types'

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

export function useLessonTypes(): UseQueryResult<LessonType[]> {
  return useQuery({
    queryKey: ['lesson-types'],
    queryFn: async () => writeCache('lesson-types', await api.lessonTypes()),
    initialData: () => readCache<LessonType[]>('lesson-types') ?? undefined,
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

/* --- Админка --- */

/** Предметы, преподаватели и аудитории для подсказок в форме изменения. */
export function useCatalog(token: string | null): UseQueryResult<Catalog> {
  return useQuery({
    queryKey: ['admin-catalog'],
    queryFn: () => api.catalog(token!),
    enabled: token !== null,
    staleTime: 10 * 60 * 1000,
  })
}

/**
 * Создание и откат временных изменений. После ответа бэкенда все недели
 * перезапрашиваются: изменение может касаться нескольких групп и недель
 * (поток, перенос через границу недели).
 */
export function useOverrideMutations(token: string) {
  const queryClient = useQueryClient()
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['schedule'] }),
    queryClient.invalidateQueries({ queryKey: ['admin-catalog'] }),
  ])

  const create = useMutation({
    mutationFn: (body: OverrideInput) => api.createOverride(token, body),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: ({ id, batch }: { id: number; batch: boolean }) => api.deleteOverride(token, id, batch),
    onSuccess: refresh,
  })
  return { create, remove }
}

/* --- Обращения --- */

/** Обращения студента с этого устройства. Ответы подтягиваются при каждом открытии раздела. */
export function useMyFeedback(enabled: boolean) {
  return useQuery({
    queryKey: ['my-feedback'],
    queryFn: () => api.myFeedback(feedbackToken()),
    enabled,
    staleTime: 30 * 1000,
  })
}

export function useSendFeedback() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: FeedbackInput) => api.sendFeedback(feedbackToken(), body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['my-feedback'] }),
  })
}

export function useFeedbackFolders(token: string) {
  return useQuery({
    queryKey: ['admin-feedback-folders'],
    queryFn: () => api.feedbackFolders(token),
    refetchInterval: 60 * 1000,
  })
}

export function useAdminFeedback(token: string, kind: string, status: string) {
  return useQuery({
    queryKey: ['admin-feedback', kind, status],
    queryFn: () => api.adminFeedback(token, kind, status),
  })
}

export function useFeedbackRecipients(token: string) {
  return useQuery({
    queryKey: ['admin-feedback-recipients'],
    queryFn: () => api.feedbackRecipients(token),
  })
}

/** Статус, перенос в папку, заметка, ответ. После ответа сервера обновляются список и счётчики папок. */
export function useFeedbackMutations(token: string) {
  const queryClient = useQueryClient()
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['admin-feedback'] }),
    queryClient.invalidateQueries({ queryKey: ['admin-feedback-folders'] }),
  ])

  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: FeedbackUpdate }) => api.updateFeedback(token, id, body),
    onSuccess: refresh,
  })
  const reply = useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) => api.replyFeedback(token, id, text),
    onSuccess: refresh,
  })
  const updateRecipient = useMutation({
    mutationFn: ({ id, body }: { id: number; body: RecipientUpdate }) => api.updateRecipient(token, id, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-feedback-recipients'] }),
  })
  return { update, reply, updateRecipient }
}
