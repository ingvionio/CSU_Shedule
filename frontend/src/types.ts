/** Основные экраны приложения. */
export type View = 'group' | 'day' | 'week' | 'feedback' | 'admin' | 'map'

export type {
  AdminFeedback,
  AdminSession,
  Day,
  FeedbackFolder,
  FeedbackKind,
  FeedbackRecipient,
  FeedbackStatus,
  Group,
  Lesson,
  LessonStatus,
  LessonType,
  MyFeedback,
  MovePoint,
  OverrideInput,
  OverrideKind,
  TimeSlot,
  Week,
  WeekSchedule,
} from './api/types'
