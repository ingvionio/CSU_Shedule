import type { Importance, MessageTargetType } from '../../types'

export const IMPORTANCE_TITLES: Record<Importance, string> = {
  low: 'Для сведения',
  normal: 'Обычное',
  high: 'Важное',
}

export const IMPORTANCE_HINTS: Record<Importance, string> = {
  low: 'Без push-уведомления и напоминаний, просто появится в разделе.',
  normal: 'Push-уведомление, подтверждение не нужно.',
  high: 'Push-уведомление и кнопка «Ознакомлен» — видно, кто подтвердил.',
}

export const TARGET_TITLES: Record<MessageTargetType, string> = {
  all: 'Всем',
  course: 'Курсу',
  direction: 'Потоку',
  group: 'Группам',
  students: 'Студентам',
}

export function messageDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}
