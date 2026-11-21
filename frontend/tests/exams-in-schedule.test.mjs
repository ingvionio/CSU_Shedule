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

const components = load('../src/ScheduleComponents.tsx')
const event = { id: 'e-1', start_time: '15:00', end_time: null, slot: 5,
  subject: 'Информатика', teacher: 'Иванов', room: '132', online_url: null, subgroup: null,
  type: { code: 'exam', name: 'Экзамен' }, status: 'changed',
  change: { original: { date: '2026-11-15', start_time: null, room: '122' } },
  event: { kind: 'session', note: 'Взять зачётку', groups: ['Своя', 'Другая'] } }
const day = { date: '2026-11-16', weekday: 1, is_today: true, lessons: [event] }
const slots = [{ number: 1, start_time: '08:00', end_time: '09:30' },
  { number: 5, start_time: '15:00', end_time: '16:30' }]

test('day card shows event badge, single time, note, other groups and struck originals', () => {
  const html = renderToStaticMarkup(React.createElement(components.DaySchedule, { day, groupName: 'Своя' }))
  assert.match(html, /schedule-event-exam/)
  assert.match(html, /event-type-badge[^>]*>Экзамен/)
  assert(html.includes('<i>15:00</i>'))
  assert.doesNotMatch(html, /15:00–|null|undefined/)
  assert.match(html, /<del>[^<]*15 ноября/)
  assert.match(html, /<del>[^<]*Время не указано/)
  assert.match(html, /<del>[^<]*122/)
  assert.match(html, /event-note[^>]*>Взять зачётку/)
  assert.match(html, /Вместе с Другая/)
  assert.doesNotMatch(html, /Вместе с Своя/)
})

test('unknown time, consultation, retake and cancelled event use server fields', () => {
  for (const [code, name] of [['consultation', 'Консультация'], ['retake', 'Пересдача'], ['credit', 'Зачёт']]) {
    const html = renderToStaticMarkup(React.createElement(components.LessonCard, {
      lesson: { ...event, type: { code, name }, start_time: null, status: 'cancelled' },
    }))
    assert.match(html, new RegExp('schedule-event-' + code))
    assert.match(html, /Время не указано/)
    assert.match(html, /Отменено/)
    assert.match(html, /cancelled/)
  }
})

test('week grid places timed events in slots, unknown times above rows and supports Sunday', () => {
  const unknown = { ...event, id: 'e-2', subject: 'Без времени', start_time: null, slot: null }
  const offGrid = { ...event, id: 'e-3', subject: 'Вне сетки', start_time: '15:15', slot: null }
  const sunday = { ...day, date: '2026-11-22', weekday: 7, lessons: [unknown, event, offGrid] }
  const tree = components.WeekGrid({ days: [sunday], slots, currentMinutes: 0, groupName: 'Своя', onLessonClick() {} })
  const html = renderToStaticMarkup(tree)
  assert.match(html, /Вс/)
  assert(html.includes('repeat(1, minmax'))
  const strip = find(tree, node => node.props.className === 'grid-untimed')
  assert.match(renderToStaticMarkup(strip), /Без времени/)
  assert.doesNotMatch(renderToStaticMarkup(strip), /Вне сетки/)
  const timedCell = find(tree, node => node.props.className?.startsWith('grid-slot') && node.props.style.gridRow === 4)
  const timedHtml = renderToStaticMarkup(timedCell)
  assert.match(timedHtml, /Информатика/)
  assert.match(timedHtml, /Вне сетки/)
  assert.doesNotMatch(timedHtml, /Без времени/)
  const card = find(tree, node => node.key?.endsWith('e-1'))
  // У студента события не открываются (обработчика событий нет)
  assert.equal(card.props.onClick, undefined)
  assert.equal(card.props.role, undefined)
  assert.doesNotMatch(html, /Нажмите, чтобы изменить/)

  // В админке событие открывается своим обработчиком, а не обработчиком пар
  const opened = []
  const adminTree = components.WeekGrid({ days: [sunday], slots, currentMinutes: 0, groupName: 'Своя',
    onLessonClick() { throw new Error('экзамен не должен открываться как пара') },
    onEventClick(item) { opened.push(item.id) } })
  const adminCard = find(adminTree, node => node.key?.endsWith('e-1'))
  assert.equal(adminCard.props.role, 'button')
  adminCard.props.onClick()
  assert.deepEqual(opened, ['e-1'])
  assert.match(renderToStaticMarkup(adminTree), /Нажмите, чтобы изменить/)
})

test('ordinary lessons retain editing and note interactions', () => {
  const lesson = { ...event, id: 'l-1', event: null, end_time: '16:30', change: null, note_key: 'note' }
  let selected
  const tree = components.WeekGrid({ days: [{ ...day, lessons: [lesson] }], slots, currentMinutes: 0,
    onLessonClick: value => { selected = value } })
  find(tree, node => node.key?.endsWith('l-1')).props.onClick()
  assert.equal(selected, lesson)
})
