import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(relative, reactOverrides = {}, modules = {}) {
  const file = new URL(relative, import.meta.url)
  // import.meta в CommonJS-контексте vm недоступен; env в тестах пустой.
  const source = readFileSync(file, 'utf8').replaceAll('import.meta.env', '({})')
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText
  const exports = {}
  // Таймеры не запускаются: события статистики в тестах никуда не уходят.
  vm.runInNewContext(code, { exports, setTimeout: () => 0, clearTimeout: () => {}, require: name => {
    if (Object.hasOwn(modules, name)) return modules[name]
    if (name === 'react') return { ...require(name), useState: value => [value, () => {}], ...reactOverrides }
    if (name.startsWith('.')) {
      const tsFile = new URL(`${name}.ts`, file)
      const dependency = existsSync(tsFile) ? tsFile : new URL(`${name}.tsx`, file)
      return load(dependency.href, reactOverrides, modules)
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
const feedbackProps = { mine: {}, updates: new Map(), onMarkSeen() {} }

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

test('help actions expose feedback only after Moodle sign-in', () => {
  let destination
  for (const authenticated of [false, true]) {
    const elements = nodes(Help({ authenticated, onNavigate: view => { destination = view } }))
    const action = target => elements.find(node => node.type === 'button' && node.key === target)
    assert.equal(Boolean(action('login')), !authenticated)
    assert.equal(Boolean(action('feedback')), authenticated)
    const contact = elements.find(node => node.props?.className === 'help-contact')
    assert.equal(Boolean(contact), authenticated)
    if (authenticated) {
      nodes(contact).find(node => node.type === 'button').props.onClick()
      assert.equal(destination, 'feedback')
      action('feedback').props.onClick()
      assert.equal(destination, 'feedback')
    }
    for (const target of ['messages', 'map', 'group', 'week']) {
      action(target).props.onClick()
      assert.equal(destination, target)
    }
  }
})

test('student and admin feedback views display markup as text', () => {
  const item = {
    id: 1, status: 'answered', kind: 'methodist', kind_title: 'Методист',
    text: '<strong>Текст обращения</strong>', created_at: '2026-11-26T00:00:00Z',
    replies: [{ id: 2, author_kind: 'staff', author_title: 'Методист',
      text: '<em>Текст ответа</em>', created_at: '2026-11-26T00:00:00Z' }],
  }
  const modules = {
    '../../ContextHelp': { ContextHelp: () => null },
    '../../api/queries': {
      useFeedbackFolders: () => ({}),
      useAdminFeedback: () => ({ data: [item] }),
      useFeedbackMutations: () => ({ update: {}, reply: {} }),
    },
  }
  const { StudentFeedback } = load('../src/pages/feedback/StudentFeedback.tsx', {
    useState: () => ['mine', () => {}],
  }, modules)
  const student = renderToStaticMarkup(StudentFeedback({ ...feedbackProps, profile: { id: 1 }, mine: { data: [item] } }))
  const { AdminFeedback } = load('../src/pages/admin/AdminFeedback.tsx', {
    useState: value => [value === null ? item.id : value, () => {}],
    useEffect() {},
  }, modules)
  const admin = renderToStaticMarkup(AdminFeedback({ token: '', onUnauthorized() {} }))
  for (const markup of [student, admin]) {
    assert.match(markup, /&lt;strong&gt;Текст обращения&lt;\/strong&gt;/)
    assert.match(markup, /&lt;em&gt;Текст ответа&lt;\/em&gt;/)
    assert.doesNotMatch(markup, /<strong>Текст обращения|<em>Текст ответа/)
  }
})

test('certificate order requires purpose and an integer number of copies', async () => {
  const profile = { id: 1, full_name: 'Иванов Иван', group_id: 2, group_name: 'ПИ 201' }
  const submissions = []
  let formValues = []
  const { StudentFeedback } = load('../src/pages/feedback/StudentFeedback.tsx', {
    useState: value => [formValues.length ? formValues.shift() : value, () => {}],
  }, {
    '../../ContextHelp': { ContextHelp: () => null },
    '../../api/queries': {
      useSendFeedback: () => ({ mutateAsync: async body => { submissions.push({ ...body }); return { id: 17 } } }),
    },
  })
  let opened = false
  const props = { ...feedbackProps, profile, onOrderCertificate: () => { opened = true }, onOpenFeedback() {} }
  const feedback = StudentFeedback({ ...props, certificateMode: false })
  nodes(feedback).find(node => node.props?.className?.includes('certificate-action')).props.onClick()
  assert.equal(opened, true)

  const screen = StudentFeedback({ ...props, certificateMode: true })
  const markup = renderToStaticMarkup(screen)
  assert.match(markup, /<dd>Иванов Иван<\/dd>/)
  assert.match(markup, /<dd>ПИ 201<\/dd>/)
  assert.doesNotMatch(markup, /name="(?:author_name|group_id)"|<textarea[^>]+required/)
  const component = nodes(screen).find(node => node.type?.name === 'CertificateForm')
  const emptyForm = component.type(component.props)
  assert.equal(nodes(emptyForm).find(node => node.props?.id === 'certificate-purpose').props.required, true)
  const count = nodes(emptyForm).find(node => node.props?.id === 'certificate-copies').props
  assert.equal(count.required, true)
  assert.equal(count.min, 1)
  assert.equal(count.step, 1)
  // Порядок useState в CertificateForm: цель, количество, способ, адрес, почта.
  for (const values of [['', '2', 'pickup'], ['  ', '2', 'pickup'], ['Для вуза', '', 'pickup'], ['Для вуза', '0', 'pickup'],
    ['Для вуза', '1.5', 'pickup'], ['Для вуза', '2'], ['Для вуза', '2', 'post', '  '], ['Для вуза', '2', 'scan', '', ''],
    ['Для вуза', '2', 'scan', '', 'не почта'], ['Для вуза', '2', 'pickup', '', 'a@b']]) {
    formValues = values
    await component.type(component.props).props.onSubmit({ preventDefault() {} })
  }
  assert.deepEqual(submissions, [])
  formValues = [' Для вуза ', '2', 'pickup', 'не нужен']
  await component.type(component.props).props.onSubmit({ preventDefault() {} })
  formValues = ['Для вуза', '1', 'post', ' 454001, Челябинск ', ' me@mail.ru ']
  await component.type(component.props).props.onSubmit({ preventDefault() {} })
  formValues = ['Для вуза', '1', 'scan', '', 'me@mail.ru']
  const scanForm = component.type(component.props)
  assert.equal(nodes(scanForm).find(node => node.props?.id === 'certificate-email').props.required, true)
  await scanForm.props.onSubmit({ preventDefault() {} })
  const base = { kind: 'certificate', purpose: 'Для вуза', text: '', website: '' }
  assert.deepEqual(submissions, [
    { ...base, copies: 2, delivery: 'pickup', address: null, email: null },
    { ...base, copies: 1, delivery: 'post', address: '454001, Челябинск', email: 'me@mail.ru' },
    { ...base, copies: 1, delivery: 'scan', address: null, email: 'me@mail.ru' },
  ])
})

test('certificate history has a badge and the admin card has status and reply controls', () => {
  const item = {
    id: 17, kind: 'certificate', kind_title: 'Справка', status: 'new',
    group_name: 'ПИ 201', author_name: 'Иванов Иван', text: '<b>Для университета</b>',
    purpose: '<i>Для работодателя</i>', copies: 2,
    created_at: '2026-11-26T00:00:00Z', replies: [],
  }
  const modules = {
    '../../ContextHelp': { ContextHelp: () => null },
    '../../api/queries': {
      useFeedbackFolders: () => ({}),
      useAdminFeedback: () => ({ data: [item] }),
      useFeedbackMutations: () => ({ update: {}, reply: {} }),
    },
  }
  const { StudentFeedback } = load('../src/pages/feedback/StudentFeedback.tsx', {
    useState: () => ['mine', () => {}],
  }, modules)
  const student = renderToStaticMarkup(StudentFeedback({ ...feedbackProps, mine: { data: [item] }, profile: { id: 1 }, certificateMode: false }))
  assert.match(student, /feedback-certificate-badge">Справка<\/span>/)

  const { AdminFeedback } = load('../src/pages/admin/AdminFeedback.tsx', {
    useState: value => [value === 'unknown' ? 'certificate' : value === null ? item.id : value, () => {}],
    useEffect() {},
  }, modules)
  const admin = renderToStaticMarkup(AdminFeedback({ token: '', onUnauthorized() {} }))
  assert.match(admin, /aria-pressed="true"><span>Справки<\/span>/)
  assert.match(admin, /ЗАКАЗ СПРАВКИ №17/)
  assert.match(admin, /<dd>Иванов Иван<\/dd>/)
  assert.match(admin, /<dd>ПИ 201<\/dd>/)
  assert.match(admin, /<dt>Количество справок<\/dt><dd>2<\/dd>/)
  assert.match(admin, /Прикрепить файл/)
  assert.match(admin, /Ответ студенту/)
  assert.match(admin, /<option value="archived">Закрыто<\/option>/)
  assert.doesNotMatch(admin, /<span>Папка<\/span>/)
  for (const markup of [student, admin]) {
    assert.match(markup, /&lt;b&gt;Для университета&lt;\/b&gt;/)
    assert.match(markup, /&lt;i&gt;Для работодателя&lt;\/i&gt;/)
  }
})

test('feedback counters in navigation and history highlight a new answer beside the closed status', () => {
  const item = { id: 17, kind: 'certificate', kind_title: 'Справка', status: 'archived',
    created_at: '2026-11-26T00:00:00Z', replies: [] }
  const { StudentFeedback } = load('../src/pages/feedback/StudentFeedback.tsx', {
    useState: () => ['mine', () => {}],
  }, { '../../ContextHelp': { ContextHelp: () => null }, '../../api/queries': {} })
  let seen
  const screen = StudentFeedback({ ...feedbackProps, profile: { id: 1 }, mine: { data: [item] },
    updates: new Map([[item.id, 'Новый ответ']]), onMarkSeen: update => { seen = update } })
  const html = renderToStaticMarkup(screen)
  assert.match(html, /Мои обращения · 1/)
  assert.match(html, /feedback-card unread/)
  assert.match(html, /Новый ответ/)
  assert.match(html, /feedback-status-archived">Закрыто/)
  const list = nodes(screen).find(node => node.type?.name === 'MyFeedbackList')
  nodes(list.type(list.props)).find(node => node.props?.className?.includes('feedback-mark-seen')).props.onClick()
  assert.equal(seen, item)

  const nav = renderToStaticMarkup(BottomNav({ view: 'day', onNavigate() {}, feedbackUnread: 1 }))
  assert.match(nav, /aria-label="непрочитанных: 1">1<\/b><\/span><span>Обращения/)
})

test('feedback read state is saved for the student and renewed by a new status or staff reply', () => {
  const saved = new Map()
  let local = null
  const { useFeedbackUpdates } = load('../src/pages/feedback/updates.ts', {
    useState: () => [local, next => { local = next }],
  }, {
    '../../api/cache': {
      readCache: key => saved.get(key),
      writeCache: (key, value) => { saved.set(key, value); return value },
    },
  })
  const initial = { id: 12, status: 'new', replies: [] }
  assert.equal(useFeedbackUpdates(1, [initial]).updates.size, 0)
  const working = { ...initial, status: 'in_progress' }
  assert.equal(useFeedbackUpdates(1, [working]).updates.get(12), 'Статус обновлён')
  const answered = { ...working, status: 'answered', replies: [{ id: 3, author_kind: 'staff' }] }
  const list = useFeedbackUpdates(1, [answered])
  assert.equal(list.updates.get(12), 'Новый ответ')
  list.markSeen(answered)
  assert.equal(useFeedbackUpdates(1, [answered]).updates.size, 0)
  local = null
  assert.equal(useFeedbackUpdates(1, [answered]).updates.size, 0)
  assert.equal(useFeedbackUpdates(2, [answered]).updates.get(12), 'Новый ответ')
  assert.equal(useFeedbackUpdates(null, [answered]).updates.size, 0)
  assert.equal(useFeedbackUpdates(1, [{ ...answered, status: 'archived' }]).updates.get(12), 'Статус обновлён')
  assert.equal(useFeedbackUpdates(1, [{ ...answered, replies: [...answered.replies, { id: 4, author_kind: 'staff' }] }]).updates.get(12), 'Новый ответ')
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

  let attempts = 0
  pageLink.ref.current = { click: () => { attempts += 1 } }
  assert.equal(effects.length, 1)
  effects[0]()
  effects[0]()
  assert.equal(attempts, 1)
})

test('the native app links to the APK hosted on the website', (t) => {
  const { Capacitor } = require('@capacitor/core')
  t.mock.method(Capacitor, 'isNativePlatform', () => true)

  const { ANDROID_APK_URL } = load('../src/pages/AndroidDownload.tsx')
  assert.equal(ANDROID_APK_URL, 'https://iit-app.ru/downloads/raspisanie-iit.apk')
})
