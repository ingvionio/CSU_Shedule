import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(path, mocks = {}, globals = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, URL, require: name => mocks[name] ?? require(name), ...globals })
  return exports
}
function find(node, predicate) {
  if (!React.isValidElement(node)) return undefined
  if (predicate(node)) return node
  for (const child of React.Children.toArray(node.props.children)) {
    const result = find(child, predicate)
    if (result) return result
  }
}
function states() {
  const values = []
  let cursor = 0
  return {
    reset() { cursor = 0 },
    hooks: { ...React, useEffect() {}, useState(initial) {
      const i = cursor++
      if (!(i in values)) values[i] = typeof initial === 'function' ? initial() : initial
      return [values[i], value => { values[i] = typeof value === 'function' ? value(values[i]) : value }]
    } },
  }
}

test('pending schedule replaces empty days in both views using the server flag', () => {
  const { DaySchedule, WeekGrid } = load('../src/ScheduleComponents.tsx')
  const day = { date: '2026-11-16', weekday: 1, is_today: true, lessons: [] }
  for (const [Component, props] of [[DaySchedule, { day }], [WeekGrid, { days: [day], slots: [], currentMinutes: 0 }]]) {
    const pending = renderToStaticMarkup(React.createElement(Component, { ...props, schedulePending: true }))
    assert.equal((pending.match(/Методист ещё не загрузил расписание, оно появится позже/g) ?? []).length, 1)
    assert.doesNotMatch(pending, /Занятий нет|week-grid|day-section/)
    const loaded = renderToStaticMarkup(React.createElement(Component, { ...props, schedulePending: false }))
    assert.doesNotMatch(loaded, /Методист ещё/)
  }
  assert.match(renderToStaticMarkup(React.createElement(DaySchedule, { day })), /Занятий нет/)
})

test('automatic messages are hidden by default and the switch changes the query', () => {
  const state = states()
  let include
  const { AdminMessages } = load('../src/pages/admin/AdminMessages.tsx', {
    react: state.hooks,
    '../../ContextHelp': { ContextHelp: () => null }, './helpContent': { adminHelpItems: [] },
    '../../api/client': { ApiError: class extends Error {} },
    '../messages/labels': { IMPORTANCE_TITLES: { normal: 'Обычное' }, messageDate: () => '16 ноября' },
    '../../api/queries': { useAdminMessages: (_, value) => {
      include = value
      return { data: value ? [{ id: 1, title: 'Изменение расписания', created_by: 'system', importance: 'normal', target_title: 'Группа ПИ 101', sent_at: '', recipients_total: 2, read_count: 1 }] : [] }
    } },
  })
  const render = () => { state.reset(); return AdminMessages({ token: 'admin', groups: [], onUnauthorized() {} }) }
  let tree = render()
  assert.equal(include, false)
  assert.doesNotMatch(renderToStaticMarkup(tree), /Изменение расписания/)
  find(tree, node => node.type === 'input' && node.props.type === 'checkbox').props.onChange({ target: { checked: true } })
  tree = render()
  assert.equal(include, true)
  assert.match(renderToStaticMarkup(tree), /автоматически/)
  assert.match(renderToStaticMarkup(tree), /Прочитали 1 из 2/)
})

test('message queries cache automatic filter separately', () => {
  const calls = []
  const { useAdminMessages } = load('../src/api/queries.ts', {
    '@tanstack/react-query': { useQuery: options => options },
    './client': { api: { adminMessages: (...args) => calls.push(args) } }, './cache': {}, './student': {},
  })
  const ordinary = useAdminMessages('token')
  const automatic = useAdminMessages('token', true)
  assert.notEqual(JSON.stringify(ordinary.queryKey), JSON.stringify(automatic.queryKey))
  ordinary.queryFn(); automatic.queryFn()
  assert.deepEqual(calls, [['token', false], ['token', true]])
})
