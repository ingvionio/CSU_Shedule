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
const cards = load('../src/pages/admin/AdminExamCard.tsx')
const group = { id: 1, name: 'ИТ1-ПИб-11', course: 1 }
const exam = { id: 1, kind: { code: 'retake', name: 'Пересдача' }, date: '2026-10-05',
  start_time: '15:15', subject: 'Информатика', teacher: 'Николаев И.Е.', room: '132а', note: 'Получить задание!',
  groups: [group.name, 'ИТ1-БИб-11'], status: 'changed', is_past: false, days_left: 3,
  type: null, change: { date: '2026-09-28', start_time: '13:15', room: '132', fields: ['date', 'start_time', 'room'] } }

test('exam mutations refresh schedule, current week and admin data', async () => {
  const invalidated = []
  const hooks = load('../src/api/queries.ts', {
    '@tanstack/react-query': { useMutation: options => options,
      useQueryClient: () => ({ invalidateQueries: value => invalidated.push(value.queryKey) }) },
    './client': {}, './cache': {}, './student': {},
  })
  const mutations = hooks.useExamMutations('token')
  await mutations.upload.onSuccess({ applied: false })
  assert.equal(invalidated.length, 0)
  for (const action of ['create', 'patch', 'cancel', 'remove', 'upload']) {
    invalidated.length = 0
    await mutations[action].onSuccess({ applied: true })
    assert.deepEqual(invalidated.map(key => key[0]), ['schedule', 'current-week', 'admin-exams', 'exam-imports'])
  }
})

test('admin preview gates application and changing file or kind invalidates it', async () => {
  const state = states()
  let applied
  let filters
  const report = { events_count: 1, applied: false, rows: [], warnings: [], mappings: [], sheets: [] }
  const mutation = { isPending: false, mutateAsync: async () => {} }
  const mutations = { create: mutation, patch: mutation, cancel: mutation, remove: mutation,
    upload: { isPending: false, mutateAsync: async args => { applied = args; return { ...report, applied: args.apply } } } }
  const { AdminExams } = load('../src/pages/admin/AdminExams.tsx', {
    react: state.hooks, '../../api/client': { ApiError: class extends Error {} }, './AdminExamCard': cards,
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

test('legacy exams route opens day and keeps schedule navigation active', () => {
  const navigation = load('../src/navigation.ts')
  assert.equal(navigation.viewFromUrl('https://localhost/#/exams', true), 'day')
  const { BottomNav } = load('../src/ScheduleComponents.tsx')
  const html = renderToStaticMarkup(React.createElement(BottomNav, { view: 'day', onNavigate() {} }))
  assert.match(html, /class="nav-item active" aria-current="page"/)
})

test('admin creates, edits, cancels, restores and deletes through mutations', async () => {
  const state = states()
  const calls = []
  const event = { ...exam, kind: 'retake', groups: [group], cancelled: false, source: 'manual',
    original: { date: '2026-09-28', start_time: '13:15', room: '132' } }
  const mutations = Object.fromEntries(['create', 'patch', 'cancel', 'remove', 'upload'].map(name => [name, {
    isPending: false, mutateAsync: async value => { calls.push({ name, value }) },
  }]))
  const query = { data: [event] }
  const { AdminExams } = load('../src/pages/admin/AdminExams.tsx', {
    react: state.hooks, '../../api/client': { ApiError: class extends Error {} }, './AdminExamCard': cards,
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

test('cards distinguish consultation and exam and show originally empty fields', () => {
  const render = (type, original) => renderToStaticMarkup(React.createElement(cards.AdminExamCard, {
    event: { ...exam, type }, original, cancelled: false,
  }))
  const consultation = render({ code: 'consultation', name: 'Консультация' }, { start_time: null, room: null })
  assert.match(consultation, /exam-type-consultation/)
  assert.match(consultation, /Консультация/)
  assert.match(consultation, /<del>Время не указано<\/del>/)
  assert.match(consultation, /<del>Аудитория не указана<\/del>/)
  const examination = render({ code: 'exam', name: 'Экзамен' }, null)
  assert.match(examination, /exam-type-exam/)
  assert.match(examination, /Экзамен/)
  assert.doesNotMatch(examination, /<del>/)
})

test('admin form saves event type and preview shows sheet groups and academic year', async () => {
  let state = states()
  const report = { events_count: 1, applied: false, warnings: [], mappings: [],
    sheets: [{ sheet: '3 курс', groups: ['ПИ-301', 'ПрИ-301'], academic_year: '2025-2026', events_count: 1 }],
    rows: [{ ...exam, kind: 'session', event_type: 'exam', sheet: '3 курс', row: 13, groups: [group], original: { room: null } }],
  }
  const mutation = { isPending: false, mutateAsync: async () => {} }
  const { AdminExams } = load('../src/pages/admin/AdminExams.tsx', {
    react: { ...React, useEffect() {}, useState: initial => state.hooks.useState(initial) },
    '../../api/client': { ApiError: class extends Error {} }, './AdminExamCard': cards,
    '../../api/queries': { useAdminExams: () => ({ data: [] }), useExamImports: () => ({ data: [] }),
      useExamMutations: () => ({ create: mutation, upload: { ...mutation, mutateAsync: async () => report } }) },
  })
  const render = () => { state.reset(); return AdminExams({ token: 'admin', groups: [group], onUnauthorized() {} }) }
  let tree = render()
  find(tree, node => node.type === 'button' && node.props.children === 'Добавить').props.onClick()
  tree = render()
  const form = find(tree, node => typeof node.type === 'function' && node.props.onSave)
  state = states()
  let saved
  const formProps = { ...form.props, onSave: async body => { saved = body } }
  state.reset()
  let formTree = form.type(formProps)
  const selector = find(formTree, node => node.type === 'select' && node.props['aria-label'] === 'Тип события')
  assert(selector)
  selector.props.onChange({ target: { value: 'graded_credit' } })
  state.reset()
  formTree = form.type(formProps)
  assert.equal(find(formTree, node => node.type === 'select' && node.props['aria-label'] === 'Тип события').props.value, 'graded_credit')
  find(formTree, node => node.type === 'form').props.onSubmit({ preventDefault() {} })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(saved.event_type, 'graded_credit')
  const uploadState = states()
  const { AdminExams: UploadAdmin } = load('../src/pages/admin/AdminExams.tsx', {
    react: uploadState.hooks, '../../api/client': { ApiError: class extends Error {} }, './AdminExamCard': cards,
    '../../api/queries': { useAdminExams: () => ({ data: [] }), useExamImports: () => ({ data: [] }),
      useExamMutations: () => ({ upload: { ...mutation, mutateAsync: async () => report } }) },
  })
  const uploadRender = () => { uploadState.reset(); return UploadAdmin({ token: 'admin', groups: [group], onUnauthorized() {} }) }
  tree = uploadRender()
  find(tree, node => node.type === 'input' && node.props.type === 'file').props.onChange({ target: { files: [{ name: 'grid.xlsx' }] } })
  tree = uploadRender()
  find(tree, node => node.type === 'button' && node.props.children === 'Проверить').props.onClick()
  await new Promise(resolve => setImmediate(resolve))
  const html = renderToStaticMarkup(uploadRender())
  assert.match(html, /2025-2026/)
  assert.match(html, /ПИ-301, ПрИ-301/)
  assert.match(html, /Экзамен/)
  assert.match(html, /<del>Аудитория не указана<\/del>/)
})
