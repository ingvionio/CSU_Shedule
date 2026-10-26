import type { FeedbackKind, FeedbackStatus } from '../../types'

/**
 * Кому можно написать. Подсказка помогает выбрать адресата; если студент
 * не уверен, есть «Не знаю, кому» — такое обращение распределит админ.
 */
export const KIND_OPTIONS: { kind: FeedbackKind; label: string; hint: string }[] = [
  { kind: 'methodist', label: 'Методисту', hint: 'Учебный процесс: расписание, занятия, практика, задолженности.' },
  { kind: 'deanery', label: 'В деканат', hint: 'Документы и справки, стипендия, приказы, военный учёт.' },
  { kind: 'dev', label: 'Разработчикам', hint: 'Ошибки в приложении и идеи, как сделать его удобнее.' },
  { kind: 'unknown', label: 'Не знаю, кому', hint: 'Передадим вопрос тому, кто за него отвечает.' },
]

export const KIND_TITLES: Record<FeedbackKind, string> = {
  dev: 'Разработчики',
  methodist: 'Методист',
  deanery: 'Деканат',
  unknown: 'Не распределено',
}

export const STATUS_TITLES: Record<FeedbackStatus, string> = {
  new: 'Новое',
  in_progress: 'В работе',
  answered: 'Есть ответ',
  archived: 'Закрыто',
}

export function feedbackDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}

export const isEmail = (value: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value.trim())
