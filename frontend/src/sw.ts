/// <reference lib="webworker" />
/**
 * Service worker приложения.
 *
 * Кэширует статику (приложение открывается без сети; данные расписания и
 * сообщений лежат в localStorage), показывает push-уведомления о сообщениях
 * и по нажатию открывает нужное сообщение.
 */

import { clientsClaim } from 'workbox-core'
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'

declare const self: ServiceWorkerGlobalScope

type PushPayload = {
  title: string
  body: string
  message_id: number
  importance: 'low' | 'normal' | 'high'
  url: string
}

self.skipWaiting()
clientsClaim()

precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()
// Любой адрес приложения открывается из закэшированного index.html; API не трогаем.
// В dev прекэш пустой, index.html в нём нет — офлайн там и не нужен.
if (import.meta.env.PROD) {
  registerRoute(new NavigationRoute(createHandlerBoundToURL('index.html'), { denylist: [/^\/api\//] }))
}

self.addEventListener('push', (event) => {
  const data: PushPayload | null = event.data ? event.data.json() : null
  if (!data) return

  event.waitUntil((async () => {
    await self.registration.showNotification(data.title, {
      body: data.body,
      tag: `message-${data.message_id}`,
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      data: { url: data.url },
      requireInteraction: data.importance === 'high',
    })
    // Открытые вкладки сразу обновляют инбокс и бейдж.
    const clients = await self.clients.matchAll({ type: 'window' })
    clients.forEach((client) => client.postMessage({ type: 'messages-updated', message_id: data.message_id }))
  })())
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = new URL((event.notification.data?.url as string | undefined) ?? '/', self.location.origin).href

  event.waitUntil((async () => {
    const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const existing = clients.find((client) => new URL(client.url).origin === self.location.origin)
    if (existing) {
      await existing.focus()
      existing.postMessage({ type: 'open-message', url })
      return
    }
    await self.clients.openWindow(url)
  })())
})
