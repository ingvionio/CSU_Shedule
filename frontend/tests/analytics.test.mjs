import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)

function load(relative, globals = {}) {
  const file = new URL(relative, import.meta.url)
  const source = readFileSync(file, 'utf8').replaceAll('import.meta.env', '({})')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports = {}
  vm.runInNewContext(code, {
    exports,
    ...globals,
    require: name => (name.startsWith('.') ? load(new URL(`${name}.ts`, file).href, globals) : require(name)),
  })
  return exports
}

test('platform: APK beats standalone, standalone is PWA, otherwise browser', () => {
  const { platformOf } = load('../src/api/analytics.ts')
  assert.equal(platformOf(true, true), 'apk')
  assert.equal(platformOf(true, false), 'apk')
  assert.equal(platformOf(false, true), 'pwa')
  assert.equal(platformOf(false, false), 'web')
})

test('app_open: first launch and a return after 30 minutes count, a short pause does not', () => {
  const { isNewAppOpen, APP_OPEN_INTERVAL_MS } = load('../src/api/analytics.ts')
  const now = 1_800_000_000_000
  assert.equal(isNewAppOpen(null, now), true)
  assert.equal(isNewAppOpen(Number.NaN, now), true)
  assert.equal(isNewAppOpen(now - APP_OPEN_INTERVAL_MS + 1, now), false)
  assert.equal(isNewAppOpen(now - APP_OPEN_INTERVAL_MS, now), true)
})

test('trackAppOpen queues one event per visit and remembers the moment', () => {
  const store = new Map()
  const timers = []
  const globals = {
    localStorage: { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) },
    setTimeout: fn => { timers.push(fn); return timers.length },
    clearTimeout: () => {},
  }
  const { trackAppOpen, markAppHidden, APP_OPEN_INTERVAL_MS } = load('../src/api/analytics.ts', globals)
  const now = 1_800_000_000_000
  trackAppOpen(now)
  trackAppOpen(now + 1000)
  assert.equal(timers.length, 1, 'одно событие за заход')
  markAppHidden(now + 2000)
  trackAppOpen(now + 2000 + APP_OPEN_INTERVAL_MS - 1)
  assert.equal(timers.length, 1, 'короткая пауза — тот же заход')
  assert.ok([...store.keys()].some(key => key.endsWith('analytics-last-active')))
})

test('funnel conversion is relative to the previous step', () => {
  const { conversion } = load('../src/pages/product/labels.ts')
  assert.equal(conversion(25, 100), '25%')
  assert.equal(conversion(1, 3), '33%')
  assert.equal(conversion(5, 0), '—')
})
