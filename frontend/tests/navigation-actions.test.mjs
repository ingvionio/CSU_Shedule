import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(relative) {
  const file = new URL(relative, import.meta.url)
  const code = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, require: name => {
    if (name === 'react') return { ...require(name), useState: value => [value, () => {}] }
    if (name.startsWith('.')) return load(new URL(`${name}.ts`, file).href)
    return require(name)
  } })
  return exports
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  return [tree, ...nodes(tree.props?.children)]
}
const { Header, Brand, BottomNav } = load('../src/ScheduleComponents.tsx')
const { Help } = load('../src/pages/Help.tsx')

test('header account action opens login; back arrow still replaces the logo', () => {
  let destination
  const onBack = () => { destination = 'back' }
  const header = Header({ title: 'Помощь', onBack, accountAction: { label: 'Войти', onClick: () => { destination = 'login' } } })
  const elements = nodes(header)
  elements.find(node => node.type === 'button' && node.props.children === 'Войти').props.onClick()
  assert.equal(destination, 'login')
  assert.equal(elements.some(node => node.type === Brand), false)
  elements.find(node => node.props?.['aria-label'] === 'Назад').props.onClick()
  assert.equal(destination, 'back')
})

test('existing logo is a keyboard-accessible home button', () => {
  let opened = false
  const brand = Brand({ onHome: () => { opened = true } })
  assert.equal(brand.type, 'button')
  assert.equal(brand.props['aria-label'], 'На главную')
  brand.props.onClick()
  assert.equal(opened, true)
})

test('help actions navigate directly and hide the login action after sign-in', () => {
  let destination
  for (const authenticated of [false, true]) {
    const elements = nodes(Help({ authenticated, onNavigate: view => { destination = view } }))
    const action = target => elements.find(node => node.type === 'button' && node.key === target)
    assert.equal(Boolean(action('login')), !authenticated)
    for (const target of ['messages', 'feedback', 'map', 'group', 'week']) {
      action(target).props.onClick()
      assert.equal(destination, target)
    }
  }
})
