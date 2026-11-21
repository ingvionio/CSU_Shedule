import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function harness() {
  let session = { profile: { id: 1, full_name: 'Студент' } }
  let pushState = 'on'
  let cursor = 0
  const states = []
  const effects = []
  const item = { id: 12, title: 'Сообщение', sent_at: '2026-11-21', importance: 'normal' }
  const source = readFileSync(new URL('../src/pages/messages/StudentMessages.tsx', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react') return {
      useState(value) {
        const index = cursor++
        if (!(index in states)) states[index] = value
        return [states[index], value => { states[index] = value }]
      },
      useEffect(effect) { effects.push(effect) },
    }
    if (name === '../../api/student') return { useStudentSession: () => session }
    if (name === '../../api/queries') return { useInbox: () => ({ data: { messages: [item] } }) }
    if (name === '../../api/push') return { usePush: () => ({ state: pushState }) }
    if (name === '../../ContextHelp') return { ContextHelp: () => null }
    if (name === './labels') return { messageDate: value => value }
    return require(name)
  } })
  return {
    render(props) { cursor = 0; return exports.StudentMessages(props) },
    flush() { for (const effect of effects.splice(0)) effect() },
    session(value) { session = value }, push(value) { pushState = value },
  }
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  return [tree, ...nodes(tree.props?.children)]
}
const component = (tree, name) => nodes(tree).find(node => typeof node.type === 'function' && node.type.name === name)

test('push message request is consumed once and closing keeps it closed on return', () => {
  const h = harness()
  let requestedId = 12
  let handled = 0
  const props = () => ({ requestedId, onRequestHandled() { requestedId = null; handled++ } })
  h.render(props())
  h.flush()
  assert.equal(handled, 1)
  const dialog = component(h.render(props()), 'MessageDialog')
  assert.equal(dialog.props.item.id, 12)
  dialog.props.onClose()
  h.flush()
  assert.equal(component(h.render(props()), 'MessageDialog'), undefined)
  h.flush()
  assert.equal(handled, 1)
})

test('pending push request survives until Moodle login', () => {
  const h = harness()
  let handled = 0
  const props = { requestedId: 12, onRequestHandled() { handled++ } }
  h.session(null)
  h.render(props)
  h.flush()
  assert.equal(handled, 0)
  h.session({ profile: { id: 1 } })
  h.render(props)
  h.flush()
  assert.equal(handled, 1)
})

test('enabled push hides its card; disabled push offers only enable', () => {
  const h = harness()
  const toggle = component(h.render({ requestedId: null, onRequestHandled() {} }), 'PushToggle')
  assert.equal(toggle.type(), null)
  h.push('off')
  const buttons = nodes(toggle.type()).filter(node => node.type === 'button')
  assert.deepEqual(buttons.map(button => button.props.children), ['Включить'])
})
