/** Общая серверная сессия студента после входа через Moodle. */

import { useEffect, useSyncExternalStore } from 'react'

import { ApiError, api } from './client'
import { clearStudentSession, feedbackToken, readStudentSession, writeStudentSession } from './cache'
import type { StudentSession } from './types'

const listeners = new Set<() => void>()
let current = readStudentSession()
let identityVersion = 0
let lastActivityAttempt = 0
let pending: { active: boolean; promise: Promise<StudentSession | null> } | null = null

function publish(session: StudentSession | null, persist = true) {
  current = session
  if (persist) {
    if (session) writeStudentSession(session)
    else clearStudentSession()
  }
  listeners.forEach((listener) => listener())
}

export async function loginWithMoodle(username: string, password: string): Promise<StudentSession> {
  const response = await api.moodleLogin(username.trim(), password, feedbackToken())
  const session = { token: response.access_token, expires_at: response.expires_at, profile: response.profile }
  identityVersion += 1
  lastActivityAttempt = Date.now()
  publish(session)
  return session
}

/** Выход завершён только после подтверждения отзыва общей серверной сессии. */
export async function logoutStudent(): Promise<void> {
  const session = current
  const version = identityVersion
  if (!session) return
  try {
    await api.moodleForget(session.token)
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) throw error
  }
  if (identityVersion === version) publish(null)
}

async function refresh(active = false): Promise<StudentSession | null> {
  if (!current) return null
  if (pending) {
    const previous = pending
    const result = await previous.promise
    return active && !previous.active && result ? refresh(true) : result
  }
  const snapshot = current
  const promise = (async () => {
    try {
      const response = await api.studentRefresh(snapshot.token, active)
      if (current === snapshot) publish({ token: response.access_token, expires_at: response.expires_at, profile: response.profile })
      return current
    } catch (error) {
      if (current === snapshot && error instanceof ApiError && error.status === 401) publish(null)
      throw error
    } finally {
      pending = null
    }
  })()
  pending = { active, promise }
  return promise
}

/** Фоновое обновление токена не отмечает пользовательскую активность. */
export async function studentToken(): Promise<string | null> {
  if (!current) return null
  if (new Date(current.expires_at).getTime() <= Date.now() + 60_000) return (await refresh())?.token ?? null
  return current.token
}

export async function asStudent<T>(call: (token: string) => Promise<T>): Promise<T> {
  const version = identityVersion
  const token = await studentToken()
  if (version !== identityVersion) throw new ApiError('Учётная запись изменилась. Повторите действие', 401)
  if (!token) throw new ApiError('Авторизуйтесь через Moodle, чтобы продолжить', 401)
  try {
    return await call(token)
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401) || !current || version !== identityVersion) throw error
    const fresh = await refresh()
    if (!fresh || version !== identityVersion) throw error
    try {
      return await call(fresh.token)
    } catch (retryError) {
      if (current === fresh && retryError instanceof ApiError && retryError.status === 401) publish(null)
      throw retryError
    }
  }
}

export async function recordVisibleActivity(): Promise<void> {
  if (!current || document.visibilityState !== 'visible' || Date.now() - lastActivityAttempt < 60_000) return
  lastActivityAttempt = Date.now()
  await refresh(true)
}

/** Только открытие/возврат и действия в видимом приложении продлевают срок. */
export function useStudentActivity(): void {
  const session = useStudentSession()
  useEffect(() => {
    const record = () => { void recordVisibleActivity().catch(() => undefined) }
    const sync = (event: StorageEvent) => {
      if (event.key === 'csu-schedule:student-session' || event.key === null) {
        const incoming = readStudentSession()
        if (!incoming || incoming.profile.id !== current?.profile.id) identityVersion += 1
        publish(incoming, false)
      }
    }
    document.addEventListener('visibilitychange', record)
    document.addEventListener('pointerdown', record)
    document.addEventListener('keydown', record)
    document.addEventListener('scroll', record, { passive: true, capture: true })
    window.addEventListener('focus', record)
    window.addEventListener('online', record)
    window.addEventListener('storage', sync)
    record()
    return () => {
      document.removeEventListener('visibilitychange', record)
      document.removeEventListener('pointerdown', record)
      document.removeEventListener('keydown', record)
      document.removeEventListener('scroll', record, true)
      window.removeEventListener('focus', record)
      window.removeEventListener('online', record)
      window.removeEventListener('storage', sync)
    }
  }, [])
  useEffect(() => {
    if (!session) return
    const delay = Math.max(250, new Date(session.expires_at).getTime() - Date.now() + 250)
    const timer = window.setTimeout(() => {
      if (document.visibilityState === 'visible') void refresh().catch(() => undefined)
    }, delay)
    return () => window.clearTimeout(timer)
  }, [session?.token, session?.expires_at])
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
