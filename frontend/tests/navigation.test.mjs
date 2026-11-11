import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const source = readFileSync(new URL('../src/navigation.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText

function harness(url, authenticated = false) {
  let state
  const listeners = new Map()
  const history = []
  const window = {
    location: { href: url },
    history: Object.fromEntries(['pushState', 'replaceState'].map(method => [method, (_, __, target) => {
      window.location.href = target.href
      history.push({ method, url: target.href })
    }])),
    scrollTo() {},
    addEventListener(name, handler) { listeners.set(name, handler) },
    removeEventListener(name) { listeners.delete(name) },
  }
  const react = {
    useState(init) { state = init(); return [state, next => { state = next }] },
    useEffect(effect) { effect() },
    useCallback(fn) { return fn },
  }
  const exports = {}
  vm.runInNewContext(code, { exports, URL, window, require: name => name === 'react' ? react : require(name) })
  const [initial, navigate] = exports.useNavigation(authenticated)
  return { initial, navigate, history, window, resolve: exports.viewFromUrl, state: () => state, restore: () => listeners.get('popstate')() }
}

test('fresh launch: browser, PWA and Capacitor root skip landing with a session', () => {
  for (const origin of ['https://schedule.example', 'https://localhost', 'http://localhost:4173']) {
    assert.equal(harness(`${origin}/`).initial, 'landing')
    assert.equal(harness(`${origin}/`, true).initial, 'day')
  }
})
test('direct links survive refresh, unknown hashes have a safe default', () => {
  const h = harness('https://localhost/')
  for (const route of ['landing', 'login', 'help', 'day', 'week', 'group', 'messages', 'feedback', 'admin', 'map']) {
    assert.equal(h.resolve(`https://localhost/#/${route}`, false), route)
    assert.equal(h.resolve(`https://localhost/#/${route}`, true), route)
  }
  assert.equal(h.resolve('https://localhost/admin', false), 'admin')
  assert.equal(h.resolve('https://localhost/#/unknown', false), 'landing')
  assert.equal(h.resolve('https://localhost/#/unknown', true), 'day')
})
test('push deep links take priority over a hash; invalid message IDs do not', () => {
  const h = harness('https://localhost/')
  assert.equal(h.resolve('https://localhost/?message=12#/landing', false), 'messages')
  for (const value of ['0', '-2', 'abc', '1.5', '']) assert.equal(h.resolve(`https://localhost/?message=${value}#/help`, false), 'help')
})
test('navigation retains origin and unrelated query parameters, replaces login and restores back', () => {
  const h = harness('https://localhost/?message=12&source=push')
  h.navigate('messages', true)
  assert.equal(h.state(), 'messages')
  assert.equal(h.history[0].method, 'replaceState')
  assert.equal(h.window.location.href, 'https://localhost/?source=push#/messages')
  h.navigate('help')
  assert.equal(h.history[1].method, 'pushState')
  h.navigate('help')
  assert.equal(h.history.length, 2)
  h.window.location.href = 'https://localhost/?source=push#/messages'
  h.restore()
  assert.equal(h.state(), 'messages')
})
