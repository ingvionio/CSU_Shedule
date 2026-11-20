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
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText
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

test('period presets end today and count days inclusively', () => {
  const { presetPeriod, periodError, addDays, daysBetween, todayLocal } = load('../src/pages/product/period.ts')
  assert.deepEqual({ ...presetPeriod('week', '2026-11-19') }, { start: '2026-11-13', end: '2026-11-19', preset: 'week' })
  assert.equal(presetPeriod('today', '2026-11-19').start, '2026-11-19')
  assert.equal(addDays('2026-03-01', -1), '2026-02-28')
  assert.equal(daysBetween('2026-01-01', '2026-12-31'), 365)
  assert.equal(periodError('2026-11-10', '2026-11-01'), 'Начало позже конца')
  assert.equal(periodError('2020-01-01', '2026-11-01'), 'Не больше 731 дней')
  assert.equal(periodError('2026-11-01', '2026-11-10'), null)
  // 23:30 UTC 18.11 — уже 19.11 в Челябинске.
  assert.equal(todayLocal(new Date('2026-11-18T23:30:00Z')), '2026-11-19')
})

test('nice scale covers the max with round steps', () => {
  const ts2 = load('../src/pages/product/charts.tsx', { ResizeObserver: class {} })
  assert.deepEqual({ ...ts2.niceScale(0) }, { top: 4, step: 1 })
  assert.deepEqual({ ...ts2.niceScale(7) }, { top: 8, step: 2 })
  assert.deepEqual({ ...ts2.niceScale(130) }, { top: 150, step: 50 })
})

test('groups roll up into bachelor courses first, then master courses', () => {
  const { coursesOf } = load('../src/pages/product/courses.ts')
  const row = (id, name, course, level, users, active) => ({ id, name, course, level, users, new: 0, active })
  const courses = coursesOf([
    row(1, 'МИТ 101', 1, 'master', 3, 1),
    row(2, 'ПИ 201', 2, 'bachelor', 5, 2),
    row(3, 'ИТ1-ПИб-11', 1, 'bachelor', 4, 4),
    row(4, 'ИТ1-БИб-11', 1, 'bachelor', 1, 0),
  ])
  // Массивы из контекста vm сравниваем как JSON: у них другой прототип.
  const plain = value => JSON.parse(JSON.stringify(value))
  assert.deepEqual(plain(courses.map(c => c.title)), ['1 курс', '2 курс', '1 курс магистратуры'])
  assert.deepEqual(plain(courses.map(c => [c.users, c.active])), [[5, 4], [5, 2], [3, 1]])
  assert.deepEqual(plain(courses[0].groups.map(g => g.name)), ['ИТ1-ПИб-11', 'ИТ1-БИб-11'])
})
