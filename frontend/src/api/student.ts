/**
 * Профиль студента с авторизацией через Moodle ИИТ ЧелГУ.
 *
 * Токен студента хранится в кэше устройства.
 * Вход через Moodle привязывает студента к академической группе расписания.
 */

import { useSyncExternalStore } from 'react'

import { ApiError, api } from './client'
import { clearStudentSession, feedbackToken, readStudentSession, writeStudentSession } from './cache'
import type { StudentSession } from './types'

const listeners = new Set<() => void>()
let current = readStudentSession()

function publish(session: StudentSession | null) {
  current = session
  if (session) {
    writeStudentSession(session)
  } else {
    clearStudentSession()
  }
  listeners.forEach((listener) => listener())
}

/** Авторизация через Moodle ЧелГУ (eu.iit.csu.ru). */
export async function loginWithMoodle(username: string, password: string): Promise<StudentSession> {
  const response = await api.moodleLogin(username.trim(), password, feedbackToken())
  const session = { token: response.access_token, expires_at: response.expires_at, profile: response.profile }
  publish(session)
  return session
}

/** Локальный выход с текущего устройства (JWT очищается). */
export function logoutStudent(): void {
  publish(null)
}

/** Сброс учетных данных на сервере и локальный выход. */
export async function forgetMoodle(): Promise<void> {
  if (current?.token) {
    try {
      await api.moodleForget(current.token)
    } catch {
      // Игнорируем сетевые ошибки
    }
  }
  logoutStudent()
}

export async function registerStudent(fullName: string, groupId: number): Promise<StudentSession> {
  const response = await api.studentRegister(fullName.trim(), groupId, feedbackToken())
  const session = { token: response.access_token, expires_at: response.expires_at, profile: response.profile }
  publish(session)
  return session
}

const isExpired = (session: StudentSession) => new Date(session.expires_at).getTime() <= Date.now() + 60_000

async function refresh(session: StudentSession): Promise<string | null> {
  if (session.profile.group_id === null) return null
  return (await registerStudent(session.profile.full_name, session.profile.group_id)).token
}

/** Токен студента, обновлённый при необходимости. null — профиля нет. */
export async function studentToken(): Promise<string | null> {
  if (!current) return null
  return isExpired(current) ? refresh(current) : current.token
}

/** Запрос от имени студента. */
export async function asStudent<T>(call: (token: string) => Promise<T>): Promise<T> {
  const token = await studentToken()
  if (!token) throw new ApiError('Авторизуйтесь через Moodle, чтобы продолжить', 401)
  try {
    return await call(token)
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401) || !current) throw error
    const fresh = await refresh(current)
    if (!fresh) throw error
    return call(fresh)
  }
}

export function useStudentSession(): StudentSession | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => current,
  )
}
