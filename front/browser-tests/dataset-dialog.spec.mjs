import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'

const id = '00000000-0000-4000-8000-000000000321'
const uri = `data://${id}`
const dataset = { id, uri, title: 'Synthetic linked Dataset', content: '{"amount":0}', revision: 1,
  lock_version: 1, can_write: true, can_manage: true, can_delete: true, read_only: false,
  global_access: 0, group_access: 0, keywords: [], created_at: '2026-01-01T00:00:00Z' }
async function fixtures(page) {
  await jsonRoute(page, `**/api/datasets/${id}`, dataset)
  await jsonRoute(page, `**/api/datasets/${id}/owner`, { owner: null, options: [] })
  await jsonRoute(page, `**/api/datasets/${id}/sharing`, { lock_version: 1, can_manage: true, level: 'private', can_write: false, grants: [], options: [], owner: null, owner_groups: [] })
}

test('a chat Dataset card opens the dedicated editor and protects unsaved drafts on dismissal', async ({ page }, testInfo) => {
  await fixtures(page)
  await jsonRoute(page, '**/api/chat/rooms/room/messages/message/previews*', [{ uri, kind: 'resource', title: dataset.title,
    description: '', metadata: {}, media_type: 'application/json', download_available: false, image_available: false, open_mode: 'inline', content_format: 'json', content: dataset.content }])
  await mount(page, 'app/chat/components/MessageResourcePreviews.vue', { props: { roomId: 'room', messageId: 'message' }, privileges: ['DATASET_EDIT'] })
  const open = () => page.locator('.resource-preview-main').click()
  await open()
  const input = page.getByRole('textbox', { name: 'JSON content', exact: true })
  await expect(input).toHaveValue('{\n  "amount": 0\n}')
  await page.screenshot({ path: testInfo.outputPath('dataset-dialog-desktop.png'), animations: 'disabled' })
  await input.fill('{')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  const discard = page.getByRole('dialog').filter({ hasText: 'Discard unsaved changes before continuing?' })
  await discard.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(discard).toHaveCount(0)
  await expect(input).toHaveValue('{')
  await page.keyboard.press('Escape')
  await discard.getByRole('button', { name: 'Discard changes', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await open()
  await expect(input).toHaveValue('{\n  "amount": 0\n}')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: testInfo.outputPath('dataset-dialog-mobile.png'), animations: 'disabled' })
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/')
})

test('the Dataset modal keeps access errors visible and can retry the authorized read', async ({ page }) => {
  await fixtures(page)
  let denied = true
  await page.route(`**/api/datasets/${id}`, route => denied
    ? route.fulfill({ status: 403, json: { detail: 'Denied' } }) : route.fulfill({ json: dataset }))
  await mount(page, 'app/dataset/components/DatasetDialog.vue', { props: { id }, privileges: ['DATASET_READ'] })
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'JSON content', exact: true })).toHaveCount(0)
  denied = false
  await page.getByRole('button', { name: 'Reload', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'JSON content', exact: true })).toHaveValue('{\n  "amount": 0\n}')
})

for (const format of ['uri', 'url']) test(`a pasted Dataset ${format} converts to a card and opens the same modal after serialization`, async ({ page }) => {
  await fixtures(page)
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<p>Keep this</p>' }, privileges: ['DATASET_READ'] })
  await page.evaluate(async () => {
    const { richLinkCard } = await import('/core/util/richText.ts')
    await window.testApp.setProps({ createLinkCard: uri => richLinkCard(uri, null) })
  })
  const input = format === 'uri' ? uri : new URL(`/dataset/${id}`, page.url()).href
  await page.locator('[data-editor-surface]').click(); await page.keyboard.press('End')
  await page.locator('[data-editor-surface]').evaluate((root, value) => {
    const data = new DataTransfer(); data.setData('text/plain', value)
    root.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  }, input)
  const link = page.getByRole('link', { name: dataset.title, exact: true })
  await expect(link).toBeVisible()
  await link.click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Show card', exact: true }).click()
  await expect(page.locator('.galaris-link-card')).toContainText(dataset.title)
  const saved = await editorHtml(page)
  expect(saved).toContain(uri); expect(saved).toContain('Keep this'); expect(saved).not.toContain('amount')
  await page.locator('.galaris-link-card a').click()
  await expect(page.getByRole('dialog').locator('.dataset-editor')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.evaluate(async content => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { content, profile: 'document' } }), saved)
  await page.getByRole('link', { name: dataset.title, exact: true }).click()
  await expect(page.getByRole('dialog').locator('.dataset-editor')).toBeVisible()
  expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/')
})

for (const width of [1440, 390]) test(`the Dataset library opens inline and keeps its filter on return at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  await fixtures(page)
  await jsonRoute(page, '**/api/datasets?*', { items: [dataset], total: 1 })
  await mount(page, 'app/dataset/pages/[[id]].vue', { route: '/dataset', privileges: ['DATASET_READ'] })
  await page.evaluate(async () => {
    window.testApp.router.addRoute({ path: '/dataset/:id?', component: { render: () => null } })
    await window.testApp.router.replace('/dataset')
  })
  const search = page.getByRole('textbox', { name: 'Search', exact: true })
  await search.fill('Synthetic')
  await page.getByRole('link', { name: dataset.title, exact: true }).click()
  const input = page.getByRole('textbox', { name: 'JSON content', exact: true })
  await expect(input).toHaveValue('{\n  "amount": 0\n}')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  if (width === 1440) {
    await expect(search).toBeVisible()
    const separator = page.getByRole('separator', { name: 'Resize Dataset list' })
    await separator.focus()
    await page.keyboard.press('ArrowRight')
    await expect(separator).toHaveAttribute('aria-valuenow', '32')
    const bounds = await separator.boundingBox()
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
    await page.mouse.down()
    await page.mouse.move(bounds.x + 100, bounds.y, { steps: 10 })
    await page.mouse.up()
    await expect.poll(async () => Number(await separator.getAttribute('aria-valuenow'))).toBeGreaterThan(32)
  }
  await page.screenshot({ path: testInfo.outputPath(`dataset-library-${width}.png`), animations: 'disabled' })
  await page.getByRole('link', { name: 'Back to list', exact: true }).click()
  await expect(search).toHaveValue('Synthetic')
  await page.getByRole('link', { name: dataset.title, exact: true }).click()
  await expect(input).toHaveValue('{\n  "amount": 0\n}')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
