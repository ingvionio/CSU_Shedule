import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

// Стенд нужно запустить со SMOKE_PREVIOUS_DIST, указывающим на сборку до обновления.
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const origin = process.env.SMOKE_ORIGIN ?? 'http://127.0.0.1:4175'
const profile = await mkdtemp(join(tmpdir(), 'iit-theme-pwa-'))
const context = await chromium.launchPersistentContext(profile, {
  channel: process.env.PLAYWRIGHT_CHANNEL,
  headless: process.env.PWA_HEADLESS !== '0',
})
const page = context.pages()[0]
page.setDefaultTimeout(12000)
const key = 'csu-schedule:appearance'
const manifestId = `${origin}/`
let installed = false
const cdp = await context.newCDPSession(page)

async function updateWorker() {
  await page.evaluate(async () => {
    window.fixtureOldController = navigator.serviceWorker.controller
    const registration = await navigator.serviceWorker.ready
    await registration.update()
  }).catch((error) => {
    if (!error.message.includes('Execution context was destroyed')) throw error
  })
  await page.waitForFunction(() => !window.fixtureOldController || navigator.serviceWorker.controller !== window.fixtureOldController)
}

try {
  await page.goto(`${origin}/#/login`)
  assert.equal(await page.locator('html').getAttribute('data-theme'), null)
  await page.locator('#moodle-username').fill('fixture')
  await page.locator('#moodle-password').fill('fixture')
  await page.locator('form button[type=submit]').click()
  await page.locator('.lesson-card').first().waitFor()
  await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller))
  const before = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage)
    .filter(([name]) => name.includes('student-session') || name.includes('selected-group'))))
  assert(Object.keys(before).length > 0)

  assert((await context.request.post(`${origin}/__fixture/activate-current`)).ok())
  await updateWorker()
  if (await page.locator('html').getAttribute('data-theme') === null) await page.reload()
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'light')
  await page.locator('.lesson-card').first().waitFor()
  assert.deepEqual(await page.evaluate((keys) => Object.fromEntries(keys.map((name) => [name, localStorage.getItem(name)])),
    Object.keys(before)), before)
  console.log('Переход со старой сборки и сохранение сессии пройдены')
  await page.goto(`${origin}/#/group`)
  await page.getByRole('combobox', { name: 'Оформление' }).selectOption('dark')
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark')
  await page.goto(`${origin}/#/day`)
  await page.locator('.lesson-card').first().waitFor()
  const precached = await page.evaluate(async () => {
    const names = await caches.keys()
    const requests = await Promise.all(names.map(async (name) => (await caches.open(name)).keys()))
    return requests.flat().some((request) => new URL(request.url).pathname === '/theme-init.js')
  })
  assert(precached)
  assert((await context.request.post(`${origin}/__fixture/revise-worker`)).ok())
  await updateWorker()
  await page.reload()
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark')
  console.log('Смена активного Service Worker сохранила тёмную тему')

  try {
    await cdp.send('PWA.install', { manifestId, installUrlOrBundleUrl: origin })
    installed = true
    await cdp.send('PWA.changeAppUserSettings', { manifestId, displayMode: 'standalone' })
    const opened = context.waitForEvent('page')
    await cdp.send('PWA.launch', { manifestId })
    const appWindow = await opened
    await appWindow.waitForFunction(() => matchMedia('(display-mode: standalone)').matches)
    await appWindow.waitForFunction(() => document.documentElement.dataset.theme === 'dark')
    await context.setOffline(true)
    await appWindow.reload()
    await appWindow.locator('.lesson-card').first().waitFor()
    assert.equal(await appWindow.locator('html').getAttribute('data-theme'), 'dark')
  } finally {
    await context.setOffline(true)
    await page.reload()
    await page.locator('.lesson-card').first().waitFor()
    assert.equal(await page.evaluate((key) => localStorage.getItem(key), key), 'dark')
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark')
    assert.equal(await page.locator('meta[name=theme-color]').getAttribute('content'), '#101a27')
    console.log('Офлайн-запуск, настройка и theme-color пройдены')
  }
  console.log('Установка и офлайн-запуск standalone пройдены')
} finally {
  if (installed) await cdp.send('PWA.uninstall', { manifestId })
  await context.close()
  await rm(profile, { recursive: true, force: true })
}
