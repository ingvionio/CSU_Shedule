import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/api/student.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status }
}

function harness({ hidden = false, expired = false } = {}) {
  let now = Date.now()
  let saved = { token: 'old-token', expires_at: new Date(now + (expired ? -1000 : 86400000)).toISOString(), profile: { id: 1, group_id: 1 } }
  const calls = []
  const effects = []
  const events = new Map()
  const timers = []
  const document = { visibilityState: hidden ? 'hidden' : 'visible', addEventListener: (n, fn) => events.set(n, fn), removeEventListener() {} }
  const window = {
    addEventListener: (n, fn) => events.set(n, fn), removeEventListener() {},
    setTimeout: fn => { timers.push(fn); return timers.length }, clearTimeout() {},
  }
  const api = {
    async studentRefresh(token, active) {
      calls.push({ token, active })
      return { access_token: 'new-token', expires_at: new Date(now + 5 * 86400000).toISOString(), profile: { id: 1, group_id: 1 } }
    },
    async moodleForget(token) { calls.push({ logout: token }) },
    async moodleLogin() { return { access_token: 'login-token', expires_at: new Date(now + 5 * 86400000).toISOString(), profile: { id: 2 } } },
  }
  const exports = {}
  vm.runInNewContext(code, {
    exports, document, window,
    Date: class extends Date { static now() { return now } },
    require(name) {
      if (name === 'react') return { useEffect: effect => effects.push(effect), useSyncExternalStore: (_, snapshot) => snapshot() }
      if (name === './client') return { ApiError, api }
      if (name === './cache') return {
        readStudentSession: () => saved, writeStudentSession: value => { saved = value },
        clearStudentSession: () => { saved = null }, feedbackToken: () => 'device-key',
      }
      throw new Error(name)
    },
  })
  return { exports, api, calls, effects, events, timers, document, saved: () => saved, advance: ms => { now += ms } }
}

test('background API reads and token refresh never record activity', async () => {
  const h = harness({ expired: true })
  assert.equal(await h.exports.asStudent(async token => token), 'new-token')
  assert.equal(h.calls.length, 1)
  assert.equal(h.calls[0].active, false)
})

test('hidden app does not send activity; visible actions are throttled', async () => {
  const h = harness({ hidden: true })
  await h.exports.recordVisibleActivity()
  assert.equal(h.calls.length, 0)
  h.document.visibilityState = 'visible'
  await Promise.all([h.exports.recordVisibleActivity(), h.exports.recordVisibleActivity()])
  assert.equal(h.calls.length, 1)
  assert.equal(h.calls[0].active, true)
  h.advance(60000)
  await h.exports.recordVisibleActivity()
  assert.equal(h.calls.length, 2)
})

test('401 clears local session and cannot fall back to registration', async () => {
  const h = harness({ expired: true })
  h.api.studentRefresh = async () => { throw new ApiError('expired', 401) }
  await assert.rejects(h.exports.studentToken(), { status: 401 })
  assert.equal(h.saved(), null)
  assert.equal(h.exports.useStudentSession(), null)
})

test('network errors preserve session and are not interpreted as logout', async () => {
  const h = harness({ expired: true })
  h.api.studentRefresh = async () => { throw new ApiError('offline', 0) }
  await assert.rejects(h.exports.studentToken(), { status: 0 })
  assert.equal(h.saved().token, 'old-token')
})

test('logout calls server and clears local session only after acknowledgement', async () => {
  const h = harness()
  let complete
  h.api.moodleForget = () => new Promise(resolve => { complete = resolve })
  const logout = h.exports.logoutStudent()
  assert.equal(h.saved().token, 'old-token')
  complete()
  await logout
  assert.equal(h.saved(), null)
})

test('failed global logout keeps session for retry', async () => {
  const h = harness()
  h.api.moodleForget = async () => { throw new ApiError('offline', 0) }
  await assert.rejects(h.exports.logoutStudent(), { status: 0 })
  assert.equal(h.saved().token, 'old-token')
})

test('late refresh cannot resurrect logged out session', async () => {
  const h = harness({ expired: true })
  let complete
  h.api.studentRefresh = () => new Promise(resolve => { complete = resolve })
  const refresh = h.exports.studentToken()
  await h.exports.logoutStudent()
  complete({ access_token: 'late-token', expires_at: '2099-01-01', profile: { id: 1 } })
  assert.equal(await refresh, null)
  assert.equal(h.saved(), null)
})

test('late refresh cannot overwrite another login', async () => {
  const h = harness({ expired: true })
  let complete
  h.api.studentRefresh = () => new Promise(resolve => { complete = resolve })
  const refresh = h.exports.studentToken()
  await h.exports.loginWithMoodle('another-user', 'password')
  complete({ access_token: 'late-token', expires_at: '2099-01-01', profile: { id: 1 } })
  await refresh
  assert.equal(h.saved().token, 'login-token')
  assert.equal(h.saved().profile.id, 2)
})

test('foreground activity is retained when passive refresh is already running', async () => {
  const h = harness({ expired: true })
  let complete
  const normal = h.api.studentRefresh
  h.api.studentRefresh = () => new Promise(resolve => { complete = resolve })
  const passive = h.exports.studentToken()
  const activity = h.exports.recordVisibleActivity()
  h.api.studentRefresh = normal
  complete({ access_token: 'passive-token', expires_at: '2099-01-01', profile: { id: 1 } })
  await Promise.all([passive, activity])
  assert.equal(h.calls.length, 1)
  assert.equal(h.calls[0].active, true)
})

test('opening the app records activity; expiry timer refreshes passively', async () => {
  const h = harness()
  h.exports.useStudentActivity()
  h.effects.forEach(effect => effect())
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(h.calls[0].active, true)
  assert.ok(h.events.has('visibilitychange'))
  assert.ok(h.events.has('pointerdown'))
  assert.ok(h.events.has('keydown'))
  h.timers[0]()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(h.calls[1].active, false)
})

test('logout clears a token refreshed while server acknowledgement was pending', async () => {
  const h = harness()
  let complete
  h.api.moodleForget = () => new Promise(resolve => { complete = resolve })
  const logout = h.exports.logoutStudent()
  await h.exports.recordVisibleActivity()
  assert.equal(h.saved().token, 'new-token')
  complete()
  await logout
  assert.equal(h.saved(), null)
})

test('late logout does not clear a new login', async () => {
  const h = harness()
  let complete
  h.api.moodleForget = () => new Promise(resolve => { complete = resolve })
  const logout = h.exports.logoutStudent()
  await h.exports.loginWithMoodle('another', 'password')
  complete()
  await logout
  assert.equal(h.saved().token, 'login-token')
})

test('a pending operation cannot silently switch to another account', async () => {
  const h = harness({ expired: true })
  let complete
  h.api.studentRefresh = () => new Promise(resolve => { complete = resolve })
  let called = false
  const request = h.exports.asStudent(async () => { called = true })
  await h.exports.loginWithMoodle('another', 'password')
  complete({ access_token: 'late-token', expires_at: '2099-01-01', profile: { id: 1 } })
  await assert.rejects(request, { status: 401 })
  assert.equal(called, false)
  assert.equal(h.saved().token, 'login-token')
})

test('401 retry cannot replay an operation under another account', async () => {
  const h = harness()
  let complete
  h.api.studentRefresh = () => new Promise(resolve => { complete = resolve })
  let count = 0
  const request = h.exports.asStudent(async () => { count += 1; throw new ApiError('expired', 401) })
  await new Promise(resolve => setImmediate(resolve))
  await h.exports.loginWithMoodle('another', 'password')
  complete({ access_token: 'late-token', expires_at: '2099-01-01', profile: { id: 1 } })
  await assert.rejects(request, { status: 401 })
  assert.equal(count, 1)
  assert.equal(h.saved().token, 'login-token')
})
