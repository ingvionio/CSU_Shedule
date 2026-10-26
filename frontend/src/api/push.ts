/**
 * Подписка этого устройства на push-уведомления о сообщениях.
 *
 * Push — только сигнал «пришло новое»: сообщения всё равно лежат в инбоксе.
 * Работает по HTTPS (или на localhost). На iPhone — только если приложение
 * добавлено на экран «Домой» (iOS 16.4+).
 */

import { useCallback, useEffect, useState } from 'react'

import { api } from './client'
import { readCache, removeCache, writeCache } from './cache'
import { asStudent } from './student'

export type PushState =
  | 'checking'
  /** Браузер не умеет push. */
  | 'unsupported'
  /** iPhone/iPad в Safari: сначала «На экран Домой». */
  | 'ios-install'
  /** На сервере не заданы VAPID-ключи. */
  | 'unconfigured'
  | 'denied'
  | 'off'
  | 'on'

const SUBSCRIPTION_KEY = 'push-subscription-id'

const isIos = () => /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches
  || (navigator as Navigator & { standalone?: boolean }).standalone === true
const supported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

/** VAPID-ключ приходит строкой base64url, браузеру нужен массив байт. */
function keyBytes(base64: string): Uint8Array {
  const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  return Uint8Array.from(atob(padded), (char) => char.charCodeAt(0))
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.ready
  return registration.pushManager.getSubscription()
}

async function detect(): Promise<PushState> {
  if (!supported()) return isIos() && !isStandalone() ? 'ios-install' : 'unsupported'
  const { public_key } = await api.pushConfig()
  if (!public_key) return 'unconfigured'
  if (Notification.permission === 'denied') return 'denied'
  const subscription = await currentSubscription()
  return subscription && readCache<number>(SUBSCRIPTION_KEY) !== null ? 'on' : 'off'
}

async function enable(): Promise<void> {
  const { public_key } = await api.pushConfig()
  if (!public_key) throw new Error('Уведомления на сервере пока не настроены')
  if (await Notification.requestPermission() !== 'granted') throw new Error('Уведомления запрещены в настройках браузера')

  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
    ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) })
  const json = subscription.toJSON()
  const saved = await asStudent((token) => api.subscribePush(token, {
    endpoint: subscription.endpoint,
    keys: { p256dh: json.keys?.p256dh ?? '', auth: json.keys?.auth ?? '' },
  }))
  writeCache(SUBSCRIPTION_KEY, saved.id)
}

async function disable(): Promise<void> {
  const id = readCache<number>(SUBSCRIPTION_KEY)
  if (id !== null) await asStudent((token) => api.unsubscribePush(token, id)).catch(() => undefined)
  removeCache(SUBSCRIPTION_KEY)
  await (await currentSubscription())?.unsubscribe()
}

export function usePush() {
  const [state, setState] = useState<PushState>('checking')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    detect().then(setState).catch(() => setState('unsupported'))
  }, [])

  useEffect(refresh, [refresh])

  const run = (action: () => Promise<void>) => async () => {
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(false)
      refresh()
    }
  }

  return { state, busy, error, enable: run(enable), disable: run(disable) }
}
