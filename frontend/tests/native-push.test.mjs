import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'

function harness(saved = null) {
  const cache = new Map(saved === null ? [] : [['push-subscription-id', saved]])
  const listeners = new Map()
  const calls = []
  const events = []
  let permission = 'granted'
  let error = false
  let nextId = saved ?? 1
  const plugin = {
    async addListener(name, callback) { listeners.set(name, callback); return { remove: async () => listeners.delete(name) } },
    async createChannel(channel) { calls.push(['channel', channel]) },
    async checkPermissions() { return { receive: permission } },
    async requestPermissions() { calls.push(['permission']); return { receive: permission } },
    async register() {
      calls.push(['register'])
      queueMicrotask(() => listeners.get(error ? 'registrationError' : 'registration')(error ? { error: 'FCM unavailable' } : { value: 'fcm-registration-token-123' }))
    },
    async unregister() { calls.push(['unregister']) },
  }
  const api = {
    pushConfig: async () => ({ fcm: true, public_key: null }),
    async subscribePush(token, body) { calls.push(['subscribe', body]); return { id: nextId } },
    async unsubscribePush(token, id) { calls.push(['delete', id]) },
  }
  const exports = {}
  const source = readFileSync(new URL('../src/api/native-push.ts', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  vm.runInNewContext(code, {
    exports, setTimeout, clearTimeout, queueMicrotask,
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail } },
    window: { dispatchEvent(event) { events.push(event) } },
    require(name) {
      if (name === '@capacitor/push-notifications') return { PushNotifications: plugin }
      if (name === './client') return { api, ApiError: class extends Error {} }
      if (name === './cache') return {
        readCache: key => cache.get(key) ?? null,
        writeCache: (key, value) => cache.set(key, value), removeCache: key => cache.delete(key),
        readStudentSession: () => ({ profile: { id: 1 } }),
      }
      if (name === './student') return { asStudent: call => call('jwt') }
      throw new Error(name)
    },
  })
  return { ...exports, api, plugin, cache, calls, events, listeners, permission: value => { permission = value }, error: value => { error = value }, nextId: value => { nextId = value } }
}

test('native detection uses server config, permission and saved subscription', async () => {
  const h = harness()
  assert.equal(await h.detectNativePush(), 'off')
  h.cache.set('push-subscription-id', 4)
  assert.equal(await h.detectNativePush(), 'on')
  h.permission('denied')
  assert.equal(await h.detectNativePush(), 'denied')
  h.api.pushConfig = async () => ({ fcm: false })
  assert.equal(await h.detectNativePush(), 'unconfigured')
})

test('enable requests permission, registers after listeners and saves the FCM subscription', async () => {
  const h = harness()
  await h.enableNativePush()
  assert.equal(h.cache.get('push-subscription-id'), 1)
  assert.equal(JSON.stringify(h.calls.find(call => call[0] === 'subscribe')[1]), JSON.stringify({ platform: 'fcm', token: 'fcm-registration-token-123' }))
  assert.ok(h.calls.find(call => call[0] === 'permission'))
  assert.equal(JSON.stringify(h.calls[0]), JSON.stringify(['channel', { id: 'messages', name: 'Сообщения', importance: 4 }]))
  await h.disableNativePush()
  assert.equal(h.cache.has('push-subscription-id'), false)
  assert.deepEqual(h.calls.slice(-2), [['delete', 1], ['unregister']])
})

test('startup re-registers enabled devices, updates rotated token, and leaves disabled devices alone', async () => {
  const off = harness()
  await off.resumeNativePush()
  assert.equal(off.calls.some(call => call[0] === 'register'), false)
  const on = harness(1)
  on.nextId(2)
  await on.resumeNativePush()
  assert.equal(on.cache.get('push-subscription-id'), 2)
  assert.ok(on.calls.some(call => call[0] === 'delete' && call[1] === 1))
})

test('denied permission and registration errors reject with useful messages', async () => {
  const denied = harness()
  denied.permission('denied')
  await assert.rejects(denied.enableNativePush(), /настройках/)
  assert.equal(denied.calls.some(call => call[0] === 'register'), false)
  const failed = harness()
  failed.error(true)
  await assert.rejects(failed.enableNativePush(), /зарегистрировать/)
  assert.equal(failed.cache.has('push-subscription-id'), false)
})

test('foreground receipt invalidates inbox through the shared event; tap passes the existing URL', async () => {
  const h = harness()
  await h.initializeNativePush()
  await h.initializeNativePush()
  h.listeners.get('pushNotificationReceived')({ data: { message_id: '12' } })
  h.listeners.get('pushNotificationActionPerformed')({ notification: { data: { url: '/?message=12' } } })
  assert.equal(JSON.stringify(h.events.map(event => event.detail)), JSON.stringify([
    { type: 'messages-updated' }, { type: 'open-message', url: '/?message=12' },
  ]))
  assert.equal(h.calls.filter(call => call[0] === 'channel').length, 1)
})

test('Android 7 can register without notification channels; other channel errors are reported', async () => {
  const old = harness()
  old.plugin.createChannel = async () => { throw { code: 'UNAVAILABLE' } }
  await old.enableNativePush()
  assert.equal(old.cache.get('push-subscription-id'), 1)
  const failed = harness()
  failed.plugin.createChannel = async () => { throw new Error('channel error') }
  await assert.rejects(failed.enableNativePush(), /channel error/)
})

test('concurrent startup registrations share one request and disabled devices retain their id on API failure', async () => {
  const h = harness(1)
  await Promise.all([h.resumeNativePush(), h.resumeNativePush()])
  assert.equal(h.calls.filter(call => call[0] === 'register').length, 1)
  h.api.unsubscribePush = async () => { throw new Error('API unavailable') }
  await assert.rejects(h.disableNativePush(), /API unavailable/)
  assert.equal(h.cache.get('push-subscription-id'), 1)
  assert.equal(h.calls.some(call => call[0] === 'unregister'), false)
})

test('rotated tokens outside register are saved and disable waits for their subscription', async () => {
  const h = harness(1)
  await h.initializeNativePush()
  h.nextId(2)
  h.listeners.get('registration')({ value: 'rotated-fcm-token-123456' })
  await h.disableNativePush()
  assert.equal(h.cache.has('push-subscription-id'), false)
  assert.deepEqual(h.calls.filter(call => call[0] === 'delete'), [['delete', 1], ['delete', 2]])
})
