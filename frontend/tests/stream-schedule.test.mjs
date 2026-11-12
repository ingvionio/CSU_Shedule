import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(path, mocks = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, require: name => mocks[name] ?? require(name) })
  return exports
}

const components = load('../src/ScheduleComponents.tsx')
const groups = [
  { id: 1, name: 'ИТ1-ПрИб-11', course: 1, level: 'bachelor', direction: 'ПрИ' },
  { id: 2, name: 'ИТ1-ПИб-11', course: 1, level: 'bachelor', direction: 'ПИ' },
  { id: 3, name: 'МИТ 101', course: 1, level: 'master', direction: 'МИТ' },
  { id: 4, name: 'ПИ 201', course: 2, level: 'bachelor', direction: 'ПИ' },
]
const lesson = { id: 'l-1', start_time: '08:00', end_time: '09:30', slot: 1, subject: 'Общая пара',
  type: { code: 'lecture', name: 'Лекция' }, room: '325', teacher: null, online_url: null,
  subgroup: null, status: 'regular', change: null, note_key: null, stream_diff: null }
const shared = { ...lesson, stream_diff: ['ИТ1-ПИб-11: ауд. 326'] }
const week = { number: 12, start_date: '2026-11-16', end_date: '2026-11-22', prev: 11, next: 13 }
const day = { date: '2026-11-16', weekday: 1, is_today: false, lessons: [lesson] }
const normal = { group: groups[0], week, days: [{ ...day, lessons: [lesson, { ...lesson, id: 'l-2', subject: 'Уникальная пара' }] }] }
const stream = { group: groups[0], week, days: [{ ...day, lessons: [shared] }] }

function find(node, predicate) {
  if (!React.isValidElement(node)) return undefined
  if (predicate(node)) return node
  for (const child of React.Children.toArray(node.props.children)) {
    const result = find(child, predicate)
    if (result) return result
  }
}

function harness() {
  const states = []
  let cursor = 0
  let requested
  const hooks = {
    ...React,
    useEffect() {},
    useState(initial) {
      const index = cursor++
      if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial
      return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value }]
    },
  }
  const queries = {
    useLessonTypes: () => ({ data: [lesson.type] }),
    useCatalog: () => ({ data: { subjects: [], rooms: [], teachers: [] } }),
    useOverrideMutations: () => ({ create: {}, remove: {} }),
    useStreamSchedule: (token, ids, number) => { requested = { token, ids: [...ids], number }; return { data: stream } },
  }
  const { AdminSchedule } = load('../src/pages/admin/AdminSchedule.tsx', {
    react: hooks, '../../api/queries': queries, '../../api/client': { ApiError: class extends Error {} },
    '../../ContextHelp': { ContextHelp: () => null }, './helpContent': { adminHelpItems: [] },
    '../../ScheduleComponents': components,
  })
  const props = { groups, groupId: 1, weekNumber: 12, schedule: normal, days: normal.days,
    slots: [{ number: 1, start_time: '08:00', end_time: '09:30' }], currentMinutes: 0, token: 'admin-token',
    onGroupChange(id) { props.groupId = id }, onWeekMove() {}, onUnauthorized() {} }
  return {
    render() { cursor = 0; return AdminSchedule(props) },
    requested: () => requested,
  }
}

test('one group retains its week; stream list separates levels and courses', () => {
  const h = harness()
  let tree = h.render()
  let html = renderToStaticMarkup(tree)
  assert.match(html, /Уникальная пара/)
  assert.doesNotMatch(html, /Показаны только пары|У групп по-разному/)
  find(tree, node => node.type === 'button' && node.props.children === 'Поток').props.onClick()
  tree = h.render()
  const list = find(tree, node => node.type === 'fieldset')
  html = renderToStaticMarkup(list)
  assert.match(html, /ИТ1-ПрИб-11/)
  assert.match(html, /ИТ1-ПИб-11/)
  assert.doesNotMatch(html, /МИТ 101|ПИ 201/)
  assert.doesNotMatch(renderToStaticMarkup(tree), /Показаны только пары/)
  find(tree, node => node.type === 'button' && node.props.children === 'Одна группа').props.onClick()
  tree = h.render()
  find(tree, node => node.type === 'select').props.onChange({ target: { value: '3' } })
  tree = h.render()
  find(tree, node => node.type === 'button' && node.props.children === 'Поток').props.onClick()
  tree = h.render()
  html = renderToStaticMarkup(find(tree, node => node.type === 'fieldset'))
  assert.match(html, /МИТ 101/)
  assert.doesNotMatch(html, /ИТ1-ПрИб-11|ИТ1-ПИб-11|ПИ 201/)
})

test('selected stream uses server data and renders caption, tooltip and dialog differences', () => {
  const h = harness()
  let tree = h.render()
  find(tree, node => node.type === 'button' && node.props.children === 'Поток').props.onClick()
  tree = h.render()
  const labels = find(tree, node => node.type === 'fieldset').props.children
  const checkbox = labels.flat().find(node => node?.type === 'label' && node.key === '2').props.children[0]
  checkbox.props.onChange()
  tree = h.render()
  assert.deepEqual(h.requested(), { token: 'admin-token', ids: [1, 2], number: 12 })
  let html = renderToStaticMarkup(tree)
  assert.match(html, /Показаны только пары, общие для всех выбранных групп \(2\)/)
  assert.doesNotMatch(html, /Уникальная пара/)
  assert.match(html, /У групп по-разному/)
  assert.match(html, /title="[^"]*ИТ1-ПИб-11: ауд\. 326/)
  find(tree, node => node.type === components.WeekGrid).props.onLessonClick(shared, day)
  tree = h.render()
  const dialog = find(tree, node => node.props.role === 'dialog')
  html = renderToStaticMarkup(dialog)
  assert.match(html, /У групп по-разному/)
  assert.match(html, /ИТ1-ПИб-11: ауд\. 326/)
})

test('removing the primary group requests the remaining group and returns to an ordinary week', () => {
  const h = harness()
  let tree = h.render()
  find(tree, node => node.type === 'button' && node.props.children === 'Поток').props.onClick()
  tree = h.render()
  const checkbox = (tree, id) => find(tree, node => node.type === 'fieldset').props.children.flat()
    .find(node => node?.type === 'label' && node.key === String(id)).props.children[0]
  checkbox(tree, 2).props.onChange()
  tree = h.render()
  checkbox(tree, 1).props.onChange()
  tree = h.render()
  assert.deepEqual(h.requested().ids, [])
  const remaining = checkbox(tree, 2)
  assert.equal(remaining.props.checked, true)
  assert.equal(checkbox(tree, 1).props.checked, false)
  assert.doesNotMatch(renderToStaticMarkup(tree), /Показаны только пары|У групп по-разному/)
})

test('cache keys retain primary identity and normalize other group order; mutations refresh streams', async () => {
  const invalidated = []
  const { useStreamSchedule, useOverrideMutations } = load('../src/api/queries.ts', {
    '@tanstack/react-query': { useQuery: value => value, useMutation: value => value,
      useQueryClient: () => ({ invalidateQueries: value => { invalidated.push(value.queryKey) } }) },
    './client': { api: {} }, './cache': {}, './student': {},
  })
  const key = ids => JSON.stringify(useStreamSchedule('token', ids, 12).queryKey)
  assert.equal(key([1, 3, 2]), key([1, 2, 3]))
  assert.notEqual(key([1, 2]), key([2, 1]))
  assert.equal(useStreamSchedule('token', [1], 12).enabled, false)
  assert.equal(useStreamSchedule('token', [1, 2], null).enabled, false)
  assert.equal(useStreamSchedule('token', [1, 2], 12).enabled, true)
  for (const action of ['create', 'remove']) {
    invalidated.length = 0
    await useOverrideMutations('token')[action].onSuccess()
    assert(invalidated.some(key => key[0] === 'schedule'))
    assert(invalidated.some(key => key[0] === 'stream-schedule'))
  }
})
