import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

// Запуск после npm run build и запуска tests/smoke_server.py.
const playwright = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const engine = process.env.PLAYWRIGHT_ENGINE ?? 'chromium'
const browser = await playwright[engine].launch({ channel: process.env.PLAYWRIGHT_CHANNEL })
const origin = process.env.SMOKE_ORIGIN ?? 'http://127.0.0.1:4175'
const screenshots = process.env.THEME_SCREENSHOTS
const key = 'csu-schedule:appearance'
const viewports = [[320, 640], [360, 800], [390, 844], [430, 932], [600, 900],
  [768, 1024], [1024, 768], [1280, 800], [1440, 900], [1920, 1080], [667, 375], [844, 390]]

const appearance = (page) => page.getByRole('combobox', { name: 'Оформление' })
const heading = (page, name) => page.getByRole('heading', { name, exact: true })
const visible = (locator) => locator.waitFor({ state: 'visible' })
const themed = (page, mode) => page.waitForFunction((expected) =>
  document.documentElement.dataset.theme === expected && getComputedStyle(document.documentElement).colorScheme === expected,
mode)

async function assertFits(page, name) {
  await page.evaluate(() => document.fonts.ready)
  const width = await page.evaluate(() => [document.documentElement.clientWidth, document.documentElement.scrollWidth])
  if (width[1] > width[0] + 1) {
    const offenders = await page.locator('body *').evaluateAll((elements, width) => elements.filter((element) => {
      const bounds = element.getBoundingClientRect()
      return bounds.width > 10 && bounds.right > width + 1 && !element.closest('.week-grid-scroll, .pl-scroll')
    }).slice(0, 15).map((element) => element.tagName + '.' + element.getAttribute('class')), width[0])
    assert.fail(`${name}: ${width.join(' / ')} (${offenders.join(', ')})`)
  }
}

async function openMenu(page) {
  await page.getByRole('button', { name: 'Меню', exact: true }).click()
  return page.locator('.role-switch-menu')
}

async function signIn(page) {
  await page.goto(`${origin}/#/login`)
  await page.locator('#moodle-username').fill('fixture')
  await page.locator('#moodle-password').fill('fixture')
  await page.locator('form button[type=submit]').click()
  await visible(page.locator('.date-cell').first())
}

async function remember(context, preference) {
  await context.addInitScript(({ key, preference }) => {
    if (localStorage.getItem(key) === null) localStorage.setItem(key, preference)
  }, { key, preference })
}

async function checkAppearance() {
  const context = await browser.newContext({ colorScheme: 'dark', serviceWorkers: 'block' })
  try {
    const page = await context.newPage()
    page.setDefaultTimeout(8000)
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto(origin)
    await themed(page, 'light')
    await page.evaluate((key) => localStorage.setItem(key, 'broken'), key)
    await page.reload()
    await themed(page, 'light')
    const menu = page.getByRole('button', { name: 'Меню', exact: true })
    await menu.focus()
    await page.keyboard.press('Enter')
    for (let i = 0; i < 4; i++) await page.keyboard.press('Tab')
    assert(await appearance(page).evaluate((element) => element === document.activeElement))
    await page.keyboard.press('End')
    await page.keyboard.press('Enter')
    await themed(page, 'dark')
    assert.equal(await appearance(page).inputValue(), 'system')
    await page.emulateMedia({ colorScheme: 'light' })
    await themed(page, 'light')
    await appearance(page).selectOption('dark')
    await themed(page, 'dark')
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.emulateMedia({ colorScheme: 'light' })
    await themed(page, 'dark')
    assert.equal(await page.locator('meta[name=theme-color]').getAttribute('content'), '#101a27')

    let releaseApp
    const waitForRelease = new Promise((resolve) => { releaseApp = resolve })
    await page.route('**/assets/main-*.js', async (route) => {
      await waitForRelease
      await route.continue()
    })
    await page.reload({ waitUntil: 'commit' })
    try {
      await themed(page, 'dark')
      assert.equal(await page.locator('#root').innerHTML(), '')
      assert.equal(await page.locator('body').evaluate((body) => getComputedStyle(body).backgroundColor), 'rgb(12, 19, 30)')
    } finally {
      releaseApp()
    }
    await page.unrouteAll({ behavior: 'wait' })
    assert.equal(await (await openMenu(page)).getByRole('combobox', { name: 'Оформление' }).inputValue(), 'dark')
    await appearance(page).selectOption('light')
    await page.emulateMedia({ colorScheme: 'dark' })
    await themed(page, 'light')
    await appearance(page).selectOption('dark')

    await signIn(page)
    await page.goto(`${origin}/#/group`)
    await visible(appearance(page))
    assert.equal(await appearance(page).inputValue(), 'dark')
    await page.getByRole('button', { name: 'Выйти на всех устройствах' }).click()
    await visible(page.locator('#landing-title'))
    await themed(page, 'dark')
    assert.equal(await page.evaluate((key) => localStorage.getItem(key), key), 'dark')
    assert.deepEqual(errors, [])
    console.log('Оформление: три режима, клавиатура, ОС, перезапуск, первая отрисовка и выход')
  } finally {
    await context.close()
  }
}

async function checkViewport(width, height, mode) {
  const mobile = width < 600 || height < 500
  const context = await browser.newContext({ viewport: { width, height }, isMobile: mobile, hasTouch: mobile,
    colorScheme: mode, serviceWorkers: 'block' })
  await remember(context, mode)
  // Внешняя карта представлена локальным документом, чтобы исключить сетевой запрос.
  await context.route('https://map.csu.ru/**', (route) => route.fulfill({ contentType: 'text/html',
    body: '<html lang="ru"><meta charset="utf-8"><body style="background:#fff;color:#152d42;font:16px sans-serif;padding:12px">Макет внешней карты ЧелГУ</body></html>' }))
  await context.route('**/downloads/raspisanie-iit.apk', (route) => route.fulfill({ status: 204 }))
  const page = await context.newPage()
  page.setDefaultTimeout(8000)
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  const device = { 390: 'phone', 768: 'tablet', 1440: 'desktop' }[width]
  const show = async (scene, locator) => {
    await visible(locator)
    await themed(page, mode)
    await assertFits(page, `${width}×${height} ${mode} ${scene}`)
    if (screenshots && device && (device === 'phone' || device === 'desktop' || ['landing', 'day', 'week', 'note', 'analytics'].includes(scene))) {
      await page.screenshot({ path: join(screenshots, `${device}-${scene}-${mode}.png`), animations: 'disabled' })
    }
  }

  try {
    await page.goto(origin)
    await show('landing', page.locator('#landing-title'))
    await openMenu(page)
    await show('appearance', appearance(page))
    await openMenu(page)
    await page.goto(`${origin}/#/help`)
    await show('help', page.locator('.faq-item').first())
    await page.goto(`${origin}/#/login`)
    await show('login', page.locator('#moodle-username'))
    assert(await page.locator('form button[type=submit]').isDisabled())
    await signIn(page)
    await page.locator('.date-cell').first().click()
    await show('day', heading(page, 'Тестовое занятие'))
    for (const state of ['changed', 'cancelled', 'schedule-event']) await visible(page.locator(`.lesson-card.${state}`).first())
    await visible(page.getByText('Перенесено', { exact: true }).first())
    const nav = page.getByRole('navigation', { name: 'Разделы приложения' })
    assert((await nav.boundingBox()).height >= 44)
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    const homework = await page.locator('.homework-panel').boundingBox()
    assert(homework.y + homework.height <= (await nav.boundingBox()).y + 1, `Домашка под навигацией при ${width}×${height}`)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.getByRole('button', { name: 'На неделю', exact: true }).click()
    await show('week', page.getByText('Тестовое занятие', { exact: true }).first())
    if (width >= 900) {
      const grid = page.locator('.week-grid-scroll')
      assert(await grid.evaluate((element) => element.scrollWidth <= element.clientWidth + 1))
    }
    await page.getByRole('button', { name: 'На день', exact: true }).click()
    const regular = page.locator('.lesson-card').first()
    if (width <= 600) await regular.click()
    else await regular.getByRole('button', { name: 'Открыть мою заметку к паре' }).click()
    const dialog = page.getByRole('dialog')
    await show('note', dialog)
    const box = await dialog.boundingBox()
    assert(box.x >= 0 && box.y >= 0 && box.x + box.width <= width + 1 && box.y + box.height <= height + 1)
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'hidden' })

    if (device || width === 320 || height === 390) {
      await page.locator('.date-cell').nth(1).click()
      await show('empty-day', page.locator('.day-section .empty-day').first())
      await page.goto(`${origin}/#/group`)
      await show('profile', appearance(page))
      await page.goto(`${origin}/#/messages`)
      await show('messages', page.getByText('Тестовое важное сообщение', { exact: true }))
      await page.getByText('Тестовое важное сообщение', { exact: true }).click()
      await show('message-detail', dialog)
      await page.goto(`${origin}/#/feedback`)
      await show('feedback', page.locator('.feedback-form'))
      await page.getByRole('button', { name: /^Мои обращения/ }).click()
      await show('feedback-history', page.getByText('Справка готова.'))
      await page.goto(`${origin}/#/feedback/certificate`)
      await show('certificate', heading(page, 'Заказать справку'))
      await page.goto(`${origin}/#/map`)
      await visible(page.frameLocator('.campus-map-frame').getByText('Макет внешней карты ЧелГУ'))
      await page.locator('.campus-map-status').waitFor({ state: 'hidden' })
      await show('map', page.locator('.campus-map-frame'))
      assert.equal(await page.locator('.campus-map-frame').evaluate((element) => getComputedStyle(element).filter), 'none')
      await page.goto(`${origin}/download/`)
      await show('download', appearance(page))
      await page.goto(`${origin}/#/admin`)
      await show('admin-login', page.locator('#admin-login'))
      await page.locator('#admin-login').fill('admin')
      await page.locator('#admin-password').fill('fixture')
      await page.locator('.admin-login').getByRole('button', { name: 'Войти', exact: true }).click()
      await show('admin-schedule', heading(page, 'Расписание'))
      await page.locator('.grid-lesson-selectable').first().click()
      await show('admin-edit', dialog)
      await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
      for (const [section, label, title] of [
        ['admin-exams', 'Сессия', 'Сессия и пересдачи'],
        ['admin-imports', 'Загрузка', 'Загрузка расписаний'],
        ['admin-messages', 'Сообщения', 'Сообщения студентам'],
        ['admin-feedback', 'Обращения', 'Обращения'],
        ['admin-homework', 'Домашка', 'Редакторы группы'],
      ]) {
        await page.locator('.admin-sections').getByRole('button', { name: label, exact: true }).click()
        await show(section, heading(page, title))
        if (section === 'admin-exams') {
          await page.getByRole('button', { name: 'Добавить', exact: true }).click()
          await show('exam-edit', dialog)
          await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
        }
      }
      await page.goto(`${origin}/statistic/`)
      await show('analytics-login', page.locator('.pl-login-card'))
      await page.getByLabel('Логин', { exact: true }).fill('admin')
      await page.getByLabel('Пароль', { exact: true }).fill('fixture')
      await page.locator('.pl-login-card button').click()
      await show('analytics', page.locator('.pl-chart').first())
      await page.locator('.pl-period > button').click()
      await show('analytics-period', page.locator('.pl-popover'))
      await page.getByRole('link', { name: 'Пользователи', exact: true }).click()
      await show('analytics-users', page.locator('.pl-table').first())
      await page.getByText('Тестовый студент', { exact: true }).first().click()
      await show('analytics-user', heading(page, 'Тестовый студент'))
    }
    assert.deepEqual(errors, [])
    console.log(`${width}×${height} ${mode}: пройдено`)
  } catch (error) {
    console.error(`${width}×${height} ${mode}: ${page.url()}`, errors)
    throw error
  } finally {
    await context.close()
  }
}

async function checkSpecialStates(mode) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: mode, serviceWorkers: 'block' })
  try {
    await remember(context, mode)
    const page = await context.newPage()
    let unblock
    const paused = new Promise((resolve) => { unblock = resolve })
    await page.route('**/api/v1/groups/1/schedule?*', async (route) => {
      await paused
      await route.fulfill({ status: 503, json: { detail: 'Расписание временно недоступно' } })
    })
    await page.goto(`${origin}/#/login`)
    await page.locator('#moodle-username').fill('fixture')
    await page.locator('#moodle-password').fill('fixture')
    await page.locator('form button[type=submit]').click()
    try {
      await visible(page.getByText('Загружаем неделю…', { exact: true }))
      await themed(page, mode)
      if (screenshots) await page.screenshot({ path: join(screenshots, `phone-loading-${mode}.png`) })
    } finally {
      unblock()
    }
    await visible(page.getByText('Расписание временно недоступно', { exact: true }))
    await assertFits(page, `${mode} ошибка API`)
    await visible(page.getByRole('button', { name: 'Повторить', exact: true }))
    if (screenshots) await page.screenshot({ path: join(screenshots, `phone-api-error-${mode}.png`) })
  } finally {
    await context.close()
  }
}

try {
  console.log(`${engine} ${browser.version()}`)
  if (screenshots) await mkdir(screenshots, { recursive: true })
  await checkAppearance()
  for (const [width, height] of viewports) {
    for (const mode of ['light', 'dark']) await checkViewport(width, height, mode)
  }
  for (const mode of ['light', 'dark']) await checkSpecialStates(mode)
  console.log('Загрузка недели и ошибка API: обе темы')
} finally {
  await browser.close()
}
