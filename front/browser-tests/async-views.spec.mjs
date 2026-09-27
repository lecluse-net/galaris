import { test, expect, mount } from './fixtures.mjs'

for (const width of [390, 1440]) {
  test(`a delayed editor preserves page input and can reopen at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    let release
    const pending = new Promise(resolve => { release = resolve })
    await page.route('**/core/util/components/CodeEditor.vue', async route => {
      await pending
      await route.continue()
    })
    await mount(page, 'test-support/browser/AsyncViewHarness.vue')
    await expect(page.getByRole('status').filter({ hasText: 'Loading' })).toBeVisible()
    await page.getByRole('textbox', { name: 'Page draft' }).fill('Unsaved mobile or desktop draft')
    await page.getByRole('button', { name: 'Toggle editor' }).click()
    release()
    await expect(page.getByRole('textbox', { name: 'Source' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Toggle editor' }).click()
    const source = page.getByRole('textbox', { name: 'Source' })
    await expect(source).toHaveValue('{"existing":true}')
    await source.fill('{"edited":true}')
    await expect(page.locator('output')).toHaveText('{"edited":true}')
    await page.getByRole('button', { name: 'Toggle editor' }).click()
    await page.getByRole('button', { name: 'Toggle editor' }).click()
    await expect(source).toHaveValue('{"edited":true}')
    await expect(page.getByRole('textbox', { name: 'Page draft' })).toHaveValue('Unsaved mobile or desktop draft')
  })

  test(`a transient loader failure retries without discarding input at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await mount(page, 'test-support/browser/AsyncViewHarness.vue', { props: { failOnce: true } })
    await page.getByRole('textbox', { name: 'Page draft' }).fill('Keep after retry')
    await expect(page.getByRole('alert')).toContainText('could not be loaded')
    await page.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Source' })).toHaveValue('{"existing":true}')
    await expect(page.getByRole('textbox', { name: 'Page draft' })).toHaveValue('Keep after retry')
  })

  test(`a failed module download keeps the rest of the page usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.route('**/core/util/components/CodeEditor.vue', route => route.abort('internetdisconnected'))
    await mount(page, 'test-support/browser/AsyncViewHarness.vue')
    await expect(page.getByRole('alert')).toContainText('could not be loaded')
    await page.getByRole('textbox', { name: 'Page draft' }).fill('Do not reload this page')
    await page.getByRole('button', { name: 'Toggle editor' }).click()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByRole('textbox', { name: 'Page draft' })).toHaveValue('Do not reload this page')
  })
}
