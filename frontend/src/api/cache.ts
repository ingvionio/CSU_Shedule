/**
 * Кэш последних ответов API на устройстве.
 *
 * Нужен для офлайна: расписание открывается тем, что успели загрузить.
 * localStorage может быть недоступен (приватный режим, запрет на данные сайта),
 * поэтому каждое обращение защищено try/catch.
 */

const PREFIX = 'csu-schedule:'

export function readCache<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

export function writeCache<T>(key: string, value: T): T {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    // Кэш — удобство, а не обязательное условие работы.
  }
  return value
}

const GROUP_KEY = 'selected-group'

export function readSelectedGroup(): number | null {
  const value = readCache<number>(GROUP_KEY)
  return typeof value === 'number' ? value : null
}

export function writeSelectedGroup(groupId: number): void {
  writeCache(GROUP_KEY, groupId)
}
