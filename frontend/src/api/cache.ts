/**
 * Кэш последних ответов API на устройстве.
 *
 * Нужен для офлайна: расписание открывается тем, что успели загрузить.
 * localStorage может быть недоступен (приватный режим, запрет на данные сайта),
 * поэтому каждое обращение защищено try/catch.
 */

import type { AdminSession } from './types'

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

export function removeCache(key: string): void {
  try {
    localStorage.removeItem(PREFIX + key)
  } catch {
    // см. writeCache
  }
}

const ADMIN_KEY = 'admin-session'

/** Сессия админа на устройстве. Истёкшая не возвращается. */
export function readAdminSession(): AdminSession | null {
  const session = readCache<AdminSession>(ADMIN_KEY)
  if (!session?.token || new Date(session.expires_at).getTime() <= Date.now()) return null
  return session
}

export function writeAdminSession(session: AdminSession): void {
  writeCache(ADMIN_KEY, session)
}

export function clearAdminSession(): void {
  removeCache(ADMIN_KEY)
}
