import type { PluginListenerHandle } from '@capacitor/core'
import { PushNotifications, type ActionPerformed, type Token } from '@capacitor/push-notifications'

import { api, ApiError } from './client'
import { readCache, readStudentSession, removeCache, writeCache } from './cache'
import { asStudent } from './student'
import type { PushState } from './push'

const SUBSCRIPTION_KEY = 'push-subscription-id'
let initialization: Promise<void> | null = null
let registration: Promise<void> | null = null
let waiting: { resolve: (token: string) => void; reject: (error: Error) => void } | null = null
let acceptingTokens = true
let lastError = ''

export const nativePushError = () => lastError

function reportError(error: unknown) {
  lastError = error instanceof Error ? error.message : 'Не удалось подключить уведомления Android'
  window.dispatchEvent(new CustomEvent('push-error', { detail: lastError }))
}

async function deleteSubscription(id: number) {
  await asStudent((token) => api.unsubscribePush(token, id)).catch((error: unknown) => {
    if (!(error instanceof ApiError && error.status === 404)) throw error
  })
}

async function saveToken(token: string) {
  const previous = readCache<number>(SUBSCRIPTION_KEY)
  const saved = await asStudent((jwt) => api.subscribePush(jwt, { platform: 'fcm', token }))
  writeCache(SUBSCRIPTION_KEY, saved.id)
  // После ротации токена устройство не должно считаться двумя подписками.
  if (previous !== null && previous !== saved.id) await deleteSubscription(previous)
}

export function initializeNativePush(): Promise<void> {
  if (initialization) return initialization
  initialization = (async () => {
    const handles: PluginListenerHandle[] = []
    try {
      await PushNotifications.createChannel({ id: 'messages', name: 'Сообщения', importance: 4 }).catch((error: unknown) => {
        // Android 7 поддерживается приложением, но ещё не имеет каналов.
        if (typeof error === 'object' && error !== null && 'code' in error && error.code === 'UNAVAILABLE') return
        throw error
      })
      handles.push(await PushNotifications.addListener('registration', (token: Token) => {
        if (waiting) waiting.resolve(token.value)
        else if (!registration && acceptingTokens && readCache<number>(SUBSCRIPTION_KEY) !== null && readStudentSession()) {
          registration = saveToken(token.value).finally(() => { registration = null })
          void registration.catch(reportError)
        }
      }))
      handles.push(await PushNotifications.addListener('registrationError', () => {
        const error = new Error('Не удалось зарегистрировать уведомления Android. Проверьте подключение и сервисы Google.')
        if (waiting) waiting.reject(error)
        else reportError(error)
      }))
      handles.push(await PushNotifications.addListener('pushNotificationReceived', () => {
        window.dispatchEvent(new CustomEvent('student-push', { detail: { type: 'messages-updated' } }))
      }))
      handles.push(await PushNotifications.addListener('pushNotificationActionPerformed', (action: ActionPerformed) => {
        const url: unknown = action.notification.data?.url
        if (typeof url === 'string') {
          window.dispatchEvent(new CustomEvent('student-push', { detail: { type: 'open-message', url } }))
        }
      }))
    } catch (error) {
      await Promise.all(handles.map((handle) => handle.remove()))
      initialization = null
      throw error
    }
  })()
  return initialization
}

export async function detectNativePush(): Promise<PushState> {
  if (!(await api.pushConfig()).fcm) return 'unconfigured'
  if ((await PushNotifications.checkPermissions()).receive === 'denied') return 'denied'
  return readCache<number>(SUBSCRIPTION_KEY) !== null ? 'on' : 'off'
}

function registerNativePush(): Promise<void> {
  if (registration) return registration
  registration = (async () => {
    const token = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        waiting = null
        reject(new Error('Не удалось дождаться регистрации уведомлений Android. Попробуйте ещё раз.'))
      }, 20_000)
      waiting = {
        resolve: (value) => { clearTimeout(timer); waiting = null; resolve(value) },
        reject: (error) => { clearTimeout(timer); waiting = null; reject(error) },
      }
      void PushNotifications.register().catch((error: unknown) => {
        waiting?.reject(new Error('Не удалось зарегистрировать уведомления Android: ' + String(error)))
      })
    })
    await saveToken(token)
    lastError = ''
  })().finally(() => { registration = null })
  return registration
}

export async function enableNativePush(): Promise<void> {
  if (!(await api.pushConfig()).fcm) throw new Error('Уведомления на сервере пока не настроены')
  await initializeNativePush()
  if ((await PushNotifications.requestPermissions()).receive !== 'granted') {
    throw new Error('Уведомления запрещены в настройках приложения Android')
  }
  acceptingTokens = true
  await registerNativePush()
}

export async function resumeNativePush(): Promise<void> {
  await initializeNativePush()
  if (readStudentSession() && await detectNativePush() === 'on') await registerNativePush()
}

export async function disableNativePush(): Promise<void> {
  acceptingTokens = false
  // Дожидаемся записи уже полученного токена, чтобы отписать именно её.
  await registration?.catch(() => undefined)
  const id = readCache<number>(SUBSCRIPTION_KEY)
  try {
    if (id !== null) await deleteSubscription(id)
    removeCache(SUBSCRIPTION_KEY)
    await PushNotifications.unregister()
  } catch (error) {
    acceptingTokens = true
    throw error
  }
}

export function startNativePush(): void {
  void resumeNativePush().catch(reportError)
}
