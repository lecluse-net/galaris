import { test, expect, mount } from './fixtures.mjs'

for (const [locale, close, width] of [['en', 'Close', 1440], ['fr', 'Fermer', 390], ['zh', '关闭', 390]]) {
  test(`toasts keep automatic expiry and allow early dismissal in ${locale}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await mount(page, 'core/util/components/HtmlPreview.vue', { locale, props: { content: '<p>Preview</p>' } })
    await page.clock.install()
    const toasts = page.locator('.q-notification')

    for (const type of ['positive', 'negative', 'warning', 'info', 'ongoing']) {
      await page.evaluate(type => window.testApp.notify({ type, message: `Synthetic ${type} notification`, timeout: 1500 }), type)
      const toast = toasts.filter({ hasText: `Synthetic ${type} notification` })
      const dismiss = toast.getByRole('button', { name: close, exact: true })
      await expect(dismiss).toHaveCount(1)
      await dismiss.focus()
      await page.keyboard.press('Enter')
      await expect(toast).toHaveCount(0)
    }

    // String notifications retain Quasar's default expiry.
    await page.evaluate(() => window.testApp.notify('Synthetic default notification'))
    await expect(toasts.getByRole('button', { name: close, exact: true })).toBeVisible()
    await page.clock.runFor(6500)
    await expect(toasts).toHaveCount(0)

    // A local action remains usable beside the cross; dismissal must not run it.
    await page.evaluate(() => {
      window.notificationActionCalls = 0
      window.testApp.notify({
        message: 'Synthetic actionable notification', timeout: 1500,
        actions: [{ label: 'Synthetic action', handler: () => { window.notificationActionCalls += 1 } }],
      })
    })
    await expect(toasts.getByRole('button', { name: 'Synthetic action', exact: true })).toBeVisible()
    await expect(toasts).toHaveCSS('opacity', '1')
    await toasts.screenshot({ path: testInfo.outputPath('toast-with-action.png') })
    await toasts.getByRole('button', { name: close, exact: true }).click()
    expect(await page.evaluate(() => window.notificationActionCalls)).toBe(0)
    await expect(toasts).toHaveCount(0)

    await page.evaluate(() => window.testApp.notify({
      message: 'Synthetic action retry', timeout: 1500,
      actions: [{ label: 'Synthetic action', handler: () => { window.notificationActionCalls += 1 } }],
    }))
    await toasts.getByRole('button', { name: 'Synthetic action', exact: true }).click()
    expect(await page.evaluate(() => window.notificationActionCalls)).toBe(1)
    await expect(toasts).toHaveCount(0)

    await page.evaluate(() => window.testApp.notify({ message: 'Synthetic timed notification', timeout: 1500 }))
    await expect(toasts.getByRole('button', { name: close, exact: true })).toBeVisible()
    await page.clock.runFor(3000)
    await expect(toasts).toHaveCount(0)

    await page.evaluate(() => window.testApp.notify({ message: 'Synthetic persistent notification', timeout: 0 }))
    await page.clock.runFor(5100)
    await expect(toasts).toContainText('Synthetic persistent notification')
    await toasts.getByRole('button', { name: close, exact: true }).click()
    await expect(toasts).toHaveCount(0)
  })
}
