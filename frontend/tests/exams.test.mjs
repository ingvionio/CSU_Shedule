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
const cards = load('../src/pages/exams/ExamCard.tsx')
const group = { id: 1, name: 'ИТ1-ПИб-11', course: 1 }
const exam = { id: 1, kind: { code: 'retake', name: 'Пересдача' }, date: '2026-10-05',
  start_time: '15:15', subject: 'Информатика', teacher: 'Николаев И.Е.', room: '132а', note: 'Получить задание!',
  groups: [group.name, 'ИТ1-БИб-11'], status: 'changed', is_past: false, days_left: 3,
  change: { date: '2026-09-28', start_time: '13:15', room: '132' } }

test('student uses server kinds, order, countdown and status, with collapsed past events', () => {
  const state = states()
  const query = { data: { group, kinds: ['session', 'retake'], events: [
    { ...exam, id: 2, kind: { code: 'session', name: 'Сессия' }, subject: 'Экзамен сессии' },
    exam, { ...exam, id: 3, date: '2026-10-04', subject: 'Прошедший экзамен', status: 'cancelled', is_past: true, days_left: -1 },
  ] } }
  const { StudentExams } = load('../src/pages/exams/StudentExams.tsx', {
    react: state.hooks, '../../api/queries': { useExams: id => { assert.equal(id, 1); return query } }, './ExamCard': cards,
  }, { navigator: { onLine: false } })
  const render = () => { state.reset(); return StudentExams({ groupId: 1 }) }
  let tree = render()
  assert.match(renderToStaticMarkup(tree), /Экзамен сессии/)
  find(tree, node => node.type === 'button' && node.props.children === 'Пересдачи').props.onClick()
  tree = render()
  const html = renderToStaticMarkup(tree)
  assert.doesNotMatch(html, /Экзамен сессии/)
  assert.match(html, /через 3 дней/)
  assert.match(html, /<del>13:15<\/del>/)
  assert.match(html, /<del>132<\/del>/)
  assert.match(html, /Вместе с ИТ1-БИб-11/)
  assert.match(html, /Получить задание!/)
  assert.match(html, /Прошедшие \(1\)/)
  assert.match(html, /Отменено/)
  assert.match(html, /Показано сохранённое расписание сессии/)
  assert.doesNotMatch(html, /<details[^>]* open/)
  assert(html.indexOf('Информатика') < html.indexOf('Прошедший экзамен'))
  query.data.kinds = ['retake']
  assert.doesNotMatch(renderToStaticMarkup(render()), /aria-label="Вид событий"/)
  query.data.events = []
  assert.match(renderToStaticMarkup(render()), /Расписание сессии пока не опубликовано/)
})

test('query cache is per group; applied mutations refresh student, admin and history', async () => {
  const invalidated = []
  const saved = []
  const api = { exams: async id => ({ group: { id }, events: [] }) }
  const hooks = load('../src/api/queries.ts', {
    '@tanstack/react-query': { useQuery: options => options, useMutation: options => options,
      useQueryClient: () => ({ invalidateQueries: value => invalidated.push(value.queryKey) }) },
    './client': { api }, './cache': { readCache: key => ({ key }), writeCache: (key, value) => { saved.push(key); return value } }, './student': {},
  })
  const query = hooks.useExams(1)
  assert.equal(query.initialData().key, 'exams-1')
  await query.queryFn()
  assert.deepEqual(saved, ['exams-1'])
  assert.notEqual(JSON.stringify(query.queryKey), JSON.stringify(hooks.useExams(2).queryKey))
  assert.equal(hooks.useExams(null).enabled, false)
  assert.equal(query.initialDataUpdatedAt, 0)
  const mutations = hooks.useExamMutations('token')
  await mutations.upload.onSuccess({ applied: false })
  assert.equal(invalidated.length, 0)
  for (const action of ['create', 'patch', 'cancel', 'remove', 'upload']) {
    invalidated.length = 0
    await mutations[action].onSuccess({ applied: true })
    assert.deepEqual(invalidated.map(key => key[0]), ['exams', 'admin-exams', 'exam-imports'])
  }
})

test('admin preview gates application and changing file or kind invalidates it', async () => {
  const state = states()
  let applied
  let filters
  const report = { events_count: 1, applied: false, rows: [], warnings: [], mappings: [] }
  const mutation = { isPending: false, mutateAsync: async () => {} }
  const mutations = { create: mutation, patch: mutation, cancel: mutation, remove: mutation,
    upload: { isPending: false, mutateAsync: async args => { applied = args; return { ...report, applied: args.apply } } } }
  const { AdminExams } = load('../src/pages/admin/AdminExams.tsx', {
    react: state.hooks, '../../api/client': { ApiError: class extends Error {} }, '../exams/ExamCard': cards,
    '../../api/queries': { useAdminExams: (_, value) => { filters = value; return { data: [] } },
      useExamImports: () => ({ data: [] }), useExamMutations: () => mutations },
  })
  const render = () => { state.reset(); return AdminExams({ token: 'admin', groups: [group], onUnauthorized() {} }) }
  const button = (tree, label) => find(tree, node => node.type === 'button' && node.props.children === label)
  let tree = render()
  assert.equal(button(tree, 'Применить').props.disabled, true)
  const file = { name: 'exams.xlsx' }
  find(tree, node => node.type === 'input' && node.props.type === 'file').props.onChange({ target: { files: [file] } })
  tree = render()
  await button(tree, 'Проверить').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  tree = render()
  assert.equal(applied.apply, false)
  assert.equal(button(tree, 'Применить').props.disabled, false)
  await button(tree, 'Применить').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  tree = render()
  assert.equal(applied.apply, true)
  assert.equal(button(tree, 'Применить').props.disabled, true)
  find(tree, node => node.type === 'select' && node.props.value === 'session').props.onChange({ target: { value: 'retake' } })
  tree = render()
  assert.equal(button(tree, 'Применить').props.disabled, true)
  const html = renderToStaticMarkup(tree)
  assert.match(html, /Ручные события останутся/)
  assert.match(html, /Все курсы/)
  assert.match(html, /Все группы/)
  assert.equal(filters.kind, '')
})

test('session route and bottom schedule navigation are restored', () => {
  const navigation = load('../src/navigation.ts')
  assert.equal(navigation.viewFromUrl('https://localhost/#/exams', true), 'exams')
  const { BottomNav } = load('../src/ScheduleComponents.tsx')
  const html = renderToStaticMarkup(React.createElement(BottomNav, { view: 'exams', onNavigate() {} }))
  assert.match(html, /class="nav-item active" aria-current="page"/)
})

test('admin creates, edits, cancels, restores and deletes through mutations', async () => {
  const state = states()
  const calls = []
  const event = { ...exam, kind: 'retake', groups: [group], cancelled: false, source: 'manual',
    original_date: '2026-09-28', original_start_time: '13:15', original_room: '132' }
  const mutations = Object.fromEntries(['create', 'patch', 'cancel', 'remove', 'upload'].map(name => [name, {
    isPending: false, mutateAsync: async value => { calls.push({ name, value }) },
  }]))
  const query = { data: [event] }
  const { AdminExams } = load('../src/pages/admin/AdminExams.tsx', {
    react: state.hooks, '../../api/client': { ApiError: class extends Error {} }, '../exams/ExamCard': cards,
    '../../api/queries': { useAdminExams: () => query, useExamImports: () => ({ data: [] }), useExamMutations: () => mutations },
  })
  const render = () => { state.reset(); return AdminExams({ token: 'admin', groups: [group], onUnauthorized() {} }) }
  const button = (tree, label) => find(tree, node => node.type === 'button' && node.props.children === label)
  const form = tree => find(tree, node => typeof node.type === 'function' && node.props.onSave)
  let tree = render()
  button(tree, 'Добавить').props.onClick()
  tree = render()
  const body = { kind: 'session', date: '2026-10-06', subject: 'История', group_ids: [1] }
  await form(tree).props.onSave(body)
  assert.equal(calls.at(-1).name, 'create')
  assert.equal(calls.at(-1).value, body)
  tree = render()
  button(tree, 'Изменить').props.onClick()
  tree = render()
  assert.equal(form(tree).props.event.id, 1)
  await form(tree).props.onSave(body)
  assert.equal(calls.at(-1).name, 'patch')
  assert.equal(calls.at(-1).value.id, 1)
  tree = render()
  button(tree, 'Отменить').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.at(-1).value.cancelled, true)
  event.cancelled = true
  tree = render()
  button(tree, 'Вернуть').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.at(-1).value.cancelled, false)
  button(tree, 'Удалить').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.at(-1).name, 'remove')
  assert.equal(calls.at(-1).value, 1)
})
