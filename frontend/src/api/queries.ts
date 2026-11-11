import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { feedbackToken, readCache, writeCache } from './cache'
import { asStudent, useStudentSession } from './student'
import type {
  Catalog,
  CurrentWeek,
  Direction,
  FeedbackInput,
  FeedbackUpdate,
  Group,
  Inbox,
  LessonType,
  MessageInput,
  OverrideInput,
  RecipientUpdate,
  TimeSlot,
  WeekSchedule,
  HomeworkInput,
  HomeworkPatch,
  NoteInput,
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
    initialDataUpdatedAt: 0,
    refetchOnMount: 'always',
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
    // Сохранённая неделя показывается сразу, но не считается свежим ответом сервера.
    initialDataUpdatedAt: 0,
    enabled: groupId !== null && week !== null,
    staleTime: 5 * 60 * 1000,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
    refetchInterval: 60 * 1000,
  })
}

/* --- Админка --- */

export function useImports(token: string) {
  return useQuery({ queryKey: ['admin-imports', token], queryFn: () => api.imports(token) })
}

export function useImportMutations(token: string) {
  const queryClient = useQueryClient()
  const refresh = async (result: { applied: boolean }) => {
    if (result.applied) await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['schedule'] }),
      queryClient.invalidateQueries({ queryKey: ['groups'] }),
      queryClient.invalidateQueries({ queryKey: ['directions'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-catalog'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-imports'] }),
    ])
  }
  const weekly = useMutation({
    mutationFn: ({ files, dryRun, skipErrors }: { files: File[]; dryRun: boolean; skipErrors: boolean }) =>
      api.importWeekly(token, files, dryRun, skipErrors),
    onSuccess: refresh,
  })
  const semester = useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) => api.importSemester(token, file, dryRun),
    onSuccess: refresh,
  })
  return { weekly, semester }
}

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

/* --- Рассылка: студент --- */

/** Направления (потоки) — для выбора группы и адресации. */
export function useDirections(): UseQueryResult<Direction[]> {
  return useQuery({
    queryKey: ['directions'],
    queryFn: async () => writeCache('directions', await api.directions()),
    initialData: () => readCache<Direction[]>('directions') ?? undefined,
    staleTime: 60 * 60 * 1000,
  })
}

/** Инбокс студента. Сохраняется на устройстве, чтобы сообщения открывались без сети. */
export function useInbox(enabled: boolean): UseQueryResult<Inbox> {
  return useQuery({
    queryKey: ['inbox'],
    queryFn: async () => writeCache('inbox', await asStudent(api.inbox)),
    initialData: () => readCache<Inbox>('inbox') ?? undefined,
    // Сохранённая копия — только чтобы было что показать: при открытии всегда спрашиваем сервер.
    initialDataUpdatedAt: 0,
    enabled,
    staleTime: 30 * 1000,
    refetchInterval: 2 * 60 * 1000,
    refetchOnWindowFocus: true,
  })
}

export function useInboxMutations() {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['inbox'] })

  const open = useMutation({
    mutationFn: (id: number) => asStudent((token) => api.openMessage(token, id)),
    onSuccess: refresh,
  })
  const acknowledge = useMutation({
    mutationFn: (id: number) => asStudent((token) => api.acknowledgeMessage(token, id)),
    onSuccess: refresh,
  })
  return { open, acknowledge }
}

export function useHomework(enabled: boolean, start?: string, end?: string) {
  const session = useStudentSession()
  return useQuery({
    queryKey: ['homework', session?.profile.id, session?.profile.group_id, start, end],
    queryFn: () => asStudent((token) => api.homework(token, start, end)),
    enabled: enabled && session !== null,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
    refetchInterval: 15 * 1000,
  })
}

export function useHomeworkMutations() {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['homework'] })
  const create = useMutation({ mutationFn: (body: HomeworkInput) => asStudent((token) => api.createHomework(token, body)), onSuccess: refresh })
  const update = useMutation({ mutationFn: ({ id, body }: { id: number; body: HomeworkPatch }) => asStudent((token) => api.updateHomework(token, id, body)), onSuccess: refresh })
  const complete = useMutation({ mutationFn: ({ id, completed }: { id: number; completed: boolean }) => asStudent((token) => api.completeHomework(token, id, completed)), onSuccess: refresh })
  return { create, update, complete }
}

export function usePersonalNotes() {
  const session = useStudentSession()
  return useQuery({
    queryKey: ['personal-notes', session?.profile.id],
    queryFn: () => asStudent(api.notes),
    enabled: session !== null,
    staleTime: 0,
    refetchOnWindowFocus: true,
  })
}

export function usePersonalNoteMutations() {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['personal-notes'] })
  return {
    save: useMutation({ mutationFn: (body: NoteInput) => asStudent((token) => api.saveNote(token, body)), onSuccess: refresh }),
    remove: useMutation({ mutationFn: ({ id, version }: { id: number; version: number }) => asStudent((token) => api.deleteNote(token, id, version)), onSuccess: refresh }),
  }
}

/* --- Рассылка: методист --- */

export function useAdminMessages(token: string) {
  return useQuery({
    queryKey: ['admin-messages'],
    queryFn: () => api.adminMessages(token),
    refetchInterval: 60 * 1000,
  })
}

export function useAdminMessage(token: string, id: number | null) {
  return useQuery({
    queryKey: ['admin-messages', id],
    queryFn: () => api.adminMessage(token, id!),
    enabled: id !== null,
  })
}

export function useStudents(token: string, params: { q?: string; course?: number; group_id?: number }, enabled: boolean) {
  return useQuery({
    queryKey: ['admin-students', params],
    queryFn: () => api.students(token, params),
    enabled,
    staleTime: 30 * 1000,
  })
}

export function useHomeworkEditors(token: string, groupId: number | null) {
  return useQuery({
    queryKey: ['homework-editors', groupId],
    queryFn: () => api.homeworkEditors(token, groupId!),
    enabled: groupId !== null,
  })
}

export function useHomeworkEditorMutations(token: string, groupId: number) {
  const queryClient = useQueryClient()
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ['homework-editors', groupId] }), queryClient.invalidateQueries({ queryKey: ['homework'] })])
  const assign = useMutation({ mutationFn: ({ userId, isPrimary }: { userId: number; isPrimary: boolean }) => api.assignHomeworkEditor(token, groupId, userId, isPrimary), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (userId: number) => api.removeHomeworkEditor(token, groupId, userId), onSuccess: refresh })
  return { assign, remove }
}

export function useMessageMutations(token: string) {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin-messages'] })

  const send = useMutation({
    mutationFn: (body: MessageInput) => api.sendMessage(token, body),
    onSuccess: refresh,
  })
  const remind = useMutation({
    mutationFn: (id: number) => api.remindMessage(token, id),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteMessage(token, id),
    onSuccess: refresh,
  })
  return { send, remind, remove }
}
