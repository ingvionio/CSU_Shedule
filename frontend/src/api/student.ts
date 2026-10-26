/**
 * Профиль студента: ФИО + группа, без пароля.
 *
 * Студент привязан к устройству тем же случайным ключом, что и обращения.
 * Истёкший токен обновляется сам: фронт повторяет регистрацию с сохранённым
 * профилем и получает того же пользователя.
 */

import { useSyncExternalStore } from 'react'

import { ApiError, api } from './client'
import { feedbackToken, readStudentSession, writeStudentSession } from './cache'
import type { StudentSession } from './types'

const listeners = new Set<() => void>()
let current = readStudentSession()

function publish(session: StudentSession) {
  current = session
  writeStudentSession(session)
  listeners.forEach((listener) => listener())
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

/** Запрос от имени студента. Токен отклонён (сменился секрет, профиль удалён) — одна повторная регистрация. */
export async function asStudent<T>(call: (token: string) => Promise<T>): Promise<T> {
  const token = await studentToken()
  if (!token) throw new ApiError('Заполните профиль, чтобы получать сообщения', 401)
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
