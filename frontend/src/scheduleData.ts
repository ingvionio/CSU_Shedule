import * as XLSX from 'xlsx'
import type { Day } from './types'

export const lessonTimes = [
  '08:00–09:30', '09:40–11:10', '11:20–12:50', '13:15–14:45',
  '15:00–16:30', '16:40–18:10', '18:20–19:50', '19:55–21:25',
]

const weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
const weekDates = ['19 октября', '20 октября', '21 октября', '22 октября', '23 октября', '24 октября']

type ParsedGroup = { name: string; prefix: string }

function parseGroupNames(value: unknown): ParsedGroup[] {
  const found: ParsedGroup[] = []
  const pattern = /(ПрИ|ПИ)(?:б)?[\s–—-]*(\d{2,3}(?:\s*,\s*\d{2,3})*)/gi

  for (const match of String(value ?? '').matchAll(pattern)) {
    const prefix = match[1].toLocaleUpperCase('ru') === 'ПИ' ? 'ПИ' : 'ПрИ'
    for (const token of match[2].split(',')) {
      const code = token.trim()
      const groupNumber = code.length === 2 ? `10${code.slice(-1)}` : code
      found.push({ name: `${prefix}-${groupNumber}`, prefix })
    }
  }

  return found
}

export async function parseSchedules(file: File): Promise<{ groups: string[]; schedules: Record<string, Day[]> }> {
  const workbook = XLSX.read(await file.arrayBuffer(), { type: 'array' })
  const schedules: Record<string, Day[]> = {}
  const groups: string[] = []

  for (const name of workbook.SheetNames) {
    const sheet = workbook.Sheets[name]
    const rows = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1, defval: '' })
    let header: { row: unknown[]; names: ParsedGroup[] } | undefined

    for (const row of rows.slice(10, 25)) {
      const names = row.flatMap(parseGroupNames)
      if (names.length > (header?.names.length ?? 0)) header = { row, names }
    }
    if (!header) continue

    const groupsInSheet = new Map<string, number>()
    header.row.forEach((cell, column) => {
      parseGroupNames(cell).forEach(({ name: groupName }) => groupsInSheet.set(groupName, column))
    })

    for (const [groupName, column] of groupsInSheet) {
      const days: Day[] = weekdays.map((dayName, index) => ({ name: dayName, date: weekDates[index], lessons: [] }))
      let dayIndex = -1

      for (let rowIndex = 0;rowIndex < rows.length;rowIndex++) {
        const day = String(rows[rowIndex][0] ?? '').trim().toLocaleLowerCase('ru')
        const foundDay = weekdays.findIndex((dayName) => dayName.toLocaleLowerCase('ru') === day)
        if (foundDay >= 0) dayIndex = foundDay
        if (dayIndex < 0) continue

        const period = Number(rows[rowIndex][1])
        if (!period || period > 8) continue

        for (let offset = 0;offset < 4;offset++) {
          const subject = String(rows[rowIndex + offset]?.[column] ?? '').trim()
          if (!subject || /^(\dН\.)?\s*(ДЕНЬ|САМОСТОЯТЕЛЬНЫХ|ЗАНЯТИЙ)$/i.test(subject)) continue

          const teacherText = String(rows[rowIndex + offset + 1]?.[column] ?? '').trim()
          if (/\b[А-ЯЁ]\.\s*[А-ЯЁ]\./i.test(subject) || /АУД\.|ДОЦЕНТ|ПРЕП/i.test(subject)) continue

          const kindMatch = subject.match(/\((ЛЕК\.|ПР\.|ЛАБ\.)\)/i)
          const weekMarker = subject.match(/^([12])Н\./i)?.[1]
          const room = teacherText.match(/АУД\.\s*([^,]+)/i)?.[1]?.trim() ?? ''
          const teacher = teacherText.replace(/,?\s*АУД\..*$/i, '').trim()
          const lessonKind = kindMatch?.[1]?.replace(/[().]/g, '') === 'ЛЕК'
            ? 'Лекция'
            : kindMatch ? 'Практика' : 'Занятие'

          days[dayIndex].lessons.push({
            time: lessonTimes[period - 1],
            subject: subject.replace(/^\dН\.\s*/i, '').replace(/\s*\([^)]*\)\s*$/, '').trim(),
            kind: lessonKind,
            parity: weekMarker ? Number(weekMarker) as 1 | 2 : undefined,
            teacher: teacher || 'Преподаватель не указан',
            room: room || '—',
          })
        }
      }

      schedules[groupName] = days.map((day) => ({
        ...day,
        lessons: day.lessons.sort((a, b) => lessonTimes.indexOf(a.time) - lessonTimes.indexOf(b.time)),
      }))
      if (!groups.includes(groupName)) groups.push(groupName)
    }
  }

  if (!groups.length) throw new Error('Не удалось найти группы ПИ или ПрИ в листах Excel')
  return { groups, schedules }
}

export const demoWeek: Day[] = [
  {
    name: 'Понедельник', date: '19 октября', lessons: [
      { time: '09:30–11:00', subject: 'Математический анализ', kind: 'Лекция', teacher: 'А. А. Смирнов', room: '312' },
      { time: '11:15–12:45', subject: 'Английский язык', kind: 'Практика', teacher: 'Е. В. Орлова', room: 'Корпус 3 · 204' },
    ]
  },
  {
    name: 'Вторник', date: '20 октября', lessons: [
      { time: '10:00–11:30', subject: 'Английский язык', kind: 'Практика', teacher: 'Е. В. Орлова', room: 'Корпус 3 · 204' },
      { time: '13:00–14:30', subject: 'Программирование', kind: 'Лабораторная', teacher: 'И. В. Петров', room: '215' },
    ]
  },
  {
    name: 'Среда', date: '21 октября', lessons: [
      { time: '13:00–14:30', previousTime: '12:00–13:30', subject: 'Алгоритмы и структуры данных', kind: 'Лекция', teacher: 'И. В. Петров', room: 'Главный корпус · 204', status: 'changed', validUntil: '30 октября' },
      { time: '15:00–16:30', subject: 'Дискретная математика', kind: 'Практика', teacher: 'М. С. Иванова', room: '317' },
    ]
  },
  {
    name: 'Четверг', date: '22 октября', lessons: [
      { time: '09:30–11:00', subject: 'Теория вероятностей', kind: 'Лекция', teacher: 'Н. В. Соколова', room: '315' },
      { time: '11:15–12:45', subject: 'Базы данных', kind: 'Лабораторная', teacher: 'Д. А. Кузнецов', room: 'Корпус 4 · 3' },
    ]
  },
  {
    name: 'Пятница', date: '23 октября', lessons: [
      { time: '11:15–12:45', subject: 'Базы данных', kind: 'Лекция', teacher: 'Д. А. Кузнецов', room: 'Корпус 4 · 3' },
      { time: '14:00–15:30', subject: 'История России', kind: 'Практика', teacher: 'О. П. Климова', room: '218', status: 'cancelled' },
    ]
  },
  { name: 'Суббота', date: '24 октября', lessons: [] },
]
