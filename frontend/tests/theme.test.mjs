import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'

const script = new URL('../public/theme-init.js', import.meta.url)

function start(stored, { dark = true, blocked = false } = {}) {
  const media = new EventTarget()
  media.matches = dark
  const window = new EventTarget()
  window.matchMedia = () => media
  window.localStorage = {
    getItem() { if (blocked) throw new Error('Storage disabled'); return stored },
    setItem(_, value) { if (blocked) throw new Error('Storage disabled'); stored = value },
  }
  const root = { dataset: {} }
  const meta = { content: '#152d42', dataset: { dark: '#101a27' } }
  runInNewContext(readFileSync(script, 'utf8'), { window, document: { documentElement: root, querySelector: () => meta } })
  return {
    ...window.iitTheme, root, meta, stored: () => stored,
    system(value) { media.matches = value; media.dispatchEvent(new Event('change')) },
    storage(key, value) {
      window.dispatchEvent(Object.assign(new Event('storage'), { key, newValue: value, storageArea: window.localStorage }))
    },
  }
}

test('отсутствующая и повреждённая настройка дают светлую тему даже в тёмной системе', () => {
  for (const stored of [null, '', 'sepia', '{"theme":"dark"}']) {
    const theme = start(stored)
    assert.equal(theme.getPreference(), 'light')
    assert.equal(theme.root.dataset.theme, 'light')
    assert.equal(theme.meta.content, '#152d42')
  }
})

test('системная тема реагирует на ОС, ручная сохраняется отдельно и переживает перезапуск', () => {
  const theme = start('dark', { dark: false })
  assert.equal(theme.root.dataset.theme, 'dark')
  assert.equal(theme.meta.content, '#101a27')
  theme.system(true)
  theme.system(false)
  assert.equal(theme.root.dataset.theme, 'dark')

  let updates = 0
  const unsubscribe = theme.subscribe(() => updates++)
  theme.setPreference('system')
  theme.system(true)
  assert.equal(theme.root.dataset.theme, 'dark')
  assert.equal(theme.stored(), 'system')
  assert.equal(start(theme.stored(), { dark: false }).root.dataset.theme, 'light')
  theme.setPreference('light')
  assert.equal(theme.root.dataset.theme, 'light')
  theme.system(false)
  theme.system(true)
  assert.equal(updates, 3)
  unsubscribe()
  theme.setPreference('dark')
  assert.equal(updates, 3)
  assert.equal(start(theme.stored(), { dark: false }).root.dataset.theme, 'dark')
})

test('вкладки синхронизируют только настройку темы, без хранилища переключатель продолжает работать', () => {
  const theme = start('light')
  theme.storage('csu-schedule:student-session', 'dark')
  assert.equal(theme.root.dataset.theme, 'light')
  theme.storage('csu-schedule:appearance', 'dark')
  assert.equal(theme.root.dataset.theme, 'dark')
  theme.storage('csu-schedule:appearance', 'broken')
  assert.equal(theme.root.dataset.theme, 'light')

  const blocked = start(null, { blocked: true })
  blocked.setPreference('dark')
  assert.equal(blocked.root.dataset.theme, 'dark')
})
