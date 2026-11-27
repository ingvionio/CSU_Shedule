import type { CertificateDelivery, FeedbackKind, FeedbackStatus, QuestionKind } from '../../types'

/**
 * Кому можно написать. Подсказка помогает выбрать адресата; если студент
 * не уверен, есть «Не знаю, кому» — такое обращение распределит админ.
 */
export const KIND_OPTIONS: { kind: QuestionKind; label: string; hint: string }[] = [
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
  certificate: 'Справки',
}

export const STATUS_TITLES: Record<FeedbackStatus, string> = {
  new: 'Новое',
  in_progress: 'В работе',
  answered: 'Есть ответ',
  archived: 'Закрыто',
}

/** Как в заявке учебной части. */
export const DELIVERY_OPTIONS: { value: CertificateDelivery; label: string }[] = [
  { value: 'pickup', label: 'Заберу лично в учебной части' },
  { value: 'scan', label: 'Требуется скан на эл.почту' },
  { value: 'post', label: 'Отправить почтой РФ' },
]

export const DELIVERY_TITLES = Object.fromEntries(
  DELIVERY_OPTIONS.map((option) => [option.value, option.label]),
) as Record<CertificateDelivery, string>

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
}

export function feedbackDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}

export const isEmail = (value: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value.trim())
