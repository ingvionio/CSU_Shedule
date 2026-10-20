export type View = 'group' | 'day' | 'week' | 'admin' | 'change' | 'preview' | 'excel'

export type Lesson = {
  time: string
  subject: string
  kind: string
  teacher: string
  room: string
  status?: 'changed' | 'cancelled'
  previousTime?: string
  validUntil?: string
  parity?: 1 | 2
}

export type Day = {
  name: string
  date: string
  lessons: Lesson[]
}
