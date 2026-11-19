import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'

// Запуск после сборки и старта smoke_server.py. Playwright устанавливается отдельно.
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href
  : 'playwright')
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL })
const origin = process.env.SMOKE_ORIGIN ?? 'http://127.0.0.1:4175'

async function assertPageFits(page) {
  const sizes = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  assert.equal(sizes.scrollWidth, sizes.width)
}

try {
  for (const [width, height] of [[320, 640], [667, 375], [768, 1024], [1024, 768], [1440, 900]]) {
    const mobile = width < 600 || height < 500
    const context = await browser.newContext({
      viewport: { width, height },
      isMobile: mobile,
      hasTouch: mobile,
      serviceWorkers: 'block',
    })
    try {
      const page = await context.newPage()
      await page.goto(`${origin}/#/login`)
      await page.locator('#moodle-username').fill('fixture')
      await page.locator('#moodle-password').fill('fixture')
      await page.locator('form button[type=submit]').click()
      await page.locator('.date-cell').first().click()
      await page.getByRole('heading', { name: /^ДлинноеНазвание/ }).waitFor()
      await assertPageFits(page)

      const nav = page.getByRole('navigation', { name: 'Разделы приложения' })
      const navHeight = (await nav.boundingBox()).height
      assert(navHeight >= 44)
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
      const homework = await page.locator('.homework-panel').boundingBox()
      assert(homework.y + homework.height <= (await nav.boundingBox()).y + 1)
      await page.getByRole('button', { name: 'На неделю', exact: true }).click()

      if (width < 900) {
        const week = page.locator('.week-days')
        await week.locator('.lesson-card').first().waitFor()
        assert.equal(await week.locator('.day-section').count(), 6)
        await page.getByRole('button', { name: /К расписанию/ }).last().click()
        assert.match(await page.evaluate(() => document.activeElement.id), /^week-day-/)
        await week.getByRole('button', { name: /ДлинноеНазвание/ }).click()
      } else {
        const grid = page.getByRole('region', { name: 'Сетка расписания на неделю' })
        await grid.getByRole('button', { name: /ДлинноеНазвание/ }).click()
        assert(await grid.evaluate((element) => element.scrollWidth <= element.clientWidth + 1))
      }
      const dialog = page.getByRole('dialog')
      await dialog.waitFor()
      const box = await dialog.boundingBox()
      assert(box.x >= 0 && box.y >= 0 && box.x + box.width <= width && box.y + box.height <= height + 1)
      await assertPageFits(page)
      await page.keyboard.press('Escape')
      await dialog.waitFor({ state: 'hidden' })
      console.log(`${width} × ${height} — день, неделя и диалог`)
    } finally {
      await context.close()
    }
  }
} finally {
  await browser.close()
}
