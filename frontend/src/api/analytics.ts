/**
 * События для статистики ЛК продукта (/statistic).
 *
 * Отправка «выстрелил и забыл»: ошибки сети не показываются и не повторяются.
 * Пишется только имя события — без текстов, логинов и паролей.
 */

import { Capacitor } from '@capacitor/core'

import { feedbackToken, readCache, readStudentSession, writeCache } from './cache'

export type ClientEvent = 'landing_view' | 'login_click' | 'login_submit' | 'app_open' | 'apk_download'
export type Platform = 'web' | 'pwa' | 'apk'

declare const __APP_VERSION__: string
export const APP_VERSION: string = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : ''

/** Новый «заход» — первое открытие или возврат после такой паузы. */
export const APP_OPEN_INTERVAL_MS = 30 * 60 * 1000
const LAST_ACTIVE_KEY = 'analytics-last-active'
const BASE_URL = (import.meta.env.VITE_API_URL ?? '') + '/api/v1'

export function platformOf(native: boolean, standalone: boolean): Platform {
  if (native) return 'apk'
  return standalone ? 'pwa' : 'web'
}

export function clientPlatform(): Platform {
  let native = false
  let standalone = false
  try {
    native = Capacitor.isNativePlatform()
  } catch {
    native = false
  }
  try {
    standalone = window.matchMedia('(display-mode: standalone)').matches
      || (navigator as Navigator & { standalone?: boolean }).standalone === true
  } catch {
    standalone = false
  }
  return platformOf(native, standalone)
}

export function isNewAppOpen(lastOpen: number | null, now: number): boolean {
  return lastOpen === null || !Number.isFinite(lastOpen) || now - lastOpen >= APP_OPEN_INTERVAL_MS
}

let queue: ClientEvent[] = []
let timer: ReturnType<typeof setTimeout> | null = null

function flush(): void {
  timer = null
  if (queue.length === 0) return
  const events = queue.splice(0, 20).map((name) => ({ name }))
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = readStudentSession()?.token
  if (token) headers.Authorization = `Bearer ${token}`
  fetch(`${BASE_URL}/events`, {
    method: 'POST',
    headers,
    keepalive: true,
    body: JSON.stringify({ device_key: feedbackToken(), platform: clientPlatform(), app_version: APP_VERSION || null, events }),
  }).catch(() => {
    // Статистика не должна мешать приложению.
  })
  if (queue.length > 0) timer = setTimeout(flush, 0)
}

/**
 * Ставит событие в очередь; соседние события уходят одним запросом.
 * `immediate` — отправить сразу, до следующего запроса к API (например, перед входом).
 */
export function track(name: ClientEvent, immediate = false): void {
  queue.push(name)
  if (immediate) {
    if (timer !== null) clearTimeout(timer)
    flush()
  } else if (timer === null) {
    timer = setTimeout(flush, 300)
  }
}

/** `app_open` при запуске и при возврате на экран после паузы в фоне. */
export function trackAppOpen(now = Date.now()): void {
  const isNew = isNewAppOpen(readCache<number>(LAST_ACTIVE_KEY), now)
  writeCache(LAST_ACTIVE_KEY, now)
  if (isNew) track('app_open')
}

/** Приложение ушло в фон: пауза отсчитывается от этого момента. */
export function markAppHidden(now = Date.now()): void {
  writeCache(LAST_ACTIVE_KEY, now)
}

/** Подписка на запуск и возвраты; возвращает отписку. */
export function watchAppOpens(): () => void {
  trackAppOpen()
  const onVisibility = () => {
    if (document.visibilityState === 'visible') trackAppOpen()
    else markAppHidden()
  }
  document.addEventListener('visibilitychange', onVisibility)
  return () => document.removeEventListener('visibilitychange', onVisibility)
}
