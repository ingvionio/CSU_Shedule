import type { View } from '../types'

type HelpAction = { label: string; target: View; guestOnly?: boolean }

export const helpActions: Partial<Record<string, readonly HelpAction[]>> = {
  login: [{ label: 'Войти через Moodle', target: 'login', guestOnly: true }],
  'login-error': [{ label: 'Создать обращение', target: 'feedback' }],
  group: [{ label: 'Открыть профиль', target: 'group' }],
  views: [{ label: 'На день', target: 'day' }, { label: 'На неделю', target: 'week' }],
  parity: [{ label: 'Открыть расписание', target: 'day' }],
  changes: [{ label: 'Открыть расписание', target: 'day' }],
  offline: [{ label: 'Открыть расписание', target: 'day' }],
  homework: [{ label: 'Открыть расписание с заданиями', target: 'day' }],
  notes: [{ label: 'Открыть расписание', target: 'day' }],
  ack: [{ label: 'Открыть сообщения', target: 'messages' }],
  map: [{ label: 'Открыть карту', target: 'map' }],
  feedback: [{ label: 'Открыть обращения', target: 'feedback' }],
  push: [{ label: 'Открыть сообщения', target: 'messages' }],
  'push-device': [{ label: 'Открыть сообщения', target: 'messages' }],
}
