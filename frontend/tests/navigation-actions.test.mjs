import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(relative, reactOverrides = {}) {
  const file = new URL(relative, import.meta.url)
  const code = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const exports = {}
  vm.runInNewContext(code, { exports, require: name => {
    if (name === 'react') return { ...require(name), useState: value => [value, () => {}], ...reactOverrides }
    if (name.startsWith('.')) {
      const tsFile = new URL(`${name}.ts`, file)
      const dependency = existsSync(tsFile) ? tsFile : new URL(`${name}.tsx`, file)
      return load(dependency.href, reactOverrides)
    }
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

test('the landing and download page link to the public APK, with one automatic attempt', () => {
  const effects = []
  const { AndroidDownload } = load('../src/pages/AndroidDownload.tsx', {
    useEffect: effect => effects.push(effect),
    useRef: current => ({ current }),
  })
  const { Landing } = load('../src/pages/Landing.tsx')
  const findDownload = tree => nodes(tree).find(node => node.type === 'a' && node.props.download)
  const landing = Landing({ authenticated: false, onStart() {}, onHelp() {}, onAdmin() {} })
  const landingLink = findDownload(landing)
  const pageLink = findDownload(AndroidDownload())

  assert.equal(landingLink.props.href, '/downloads/raspisanie-iit.apk')
  assert.equal(pageLink.props.href, landingLink.props.href)
  assert.ok(existsSync(new URL(`../public${pageLink.props.href}`, import.meta.url)))

  let attempts = 0
  pageLink.ref.current = { click: () => { attempts += 1 } }
  assert.equal(effects.length, 1)
  effects[0]()
  effects[0]()
  assert.equal(attempts, 1)
})
