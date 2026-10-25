/** Основные экраны приложения. */
export type View = 'group' | 'day' | 'week' | 'admin' | 'map'

export type {
  AdminSession,
  Day,
  Group,
  Lesson,
  LessonStatus,
  LessonType,
  MovePoint,
  OverrideInput,
  OverrideKind,
  TimeSlot,
  Week,
  WeekSchedule,
} from './api/types'
