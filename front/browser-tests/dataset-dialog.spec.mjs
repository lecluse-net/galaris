import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

const id = '00000000-0000-4000-8000-000000000321'
const uri = `data://${id}`
const dataset = { id, uri, title: 'Synthetic linked Dataset', content: '{"amount":0}', revision: 1,
  lock_version: 1, can_write: true, can_manage: true, can_delete: true, read_only: false,
  global_access: 0, group_access: 0, keywords: [], created_at: '2026-01-01T00:00:00Z' }
async function fixtures(page) {
  const item = { ...documentFixture, id, title: dataset.title, document_type: 'data', media_type: 'application/json', payload: { text: dataset.content } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, `**/api/documents/${id}/attachments*`, [])
  await jsonRoute(page, new RegExp('/api/documents/' + id + '(?:\\?|$)'), { item, agent_id: null })
  await jsonRoute(page, '**/api/datasets/tags', [])
  await jsonRoute(page, '**/api/datasets/library/facets', { owners: [], keywords: [], current_user_id: 1 })
  await jsonRoute(page, `**/api/datasets/${id}`, dataset)
  await jsonRoute(page, `**/api/datasets/${id}/owner`, { owner: null, options: [] })
  await jsonRoute(page, `**/api/datasets/${id}/sharing`, { lock_version: 1, can_manage: true, level: 'private', can_write: false, grants: [], options: [], owner: null, owner_groups: [] })
}

test('a chat Data card uses the common editor and retains invalid drafts on dismissal', async ({ page }, testInfo) => {
  await fixtures(page)
  await jsonRoute(page, '**/api/chat/rooms/room/messages/message/previews*', [{ uri, kind: 'resource', title: dataset.title,
    description: '', metadata: {}, media_type: 'application/json', download_available: false, image_available: false, open_mode: 'inline', content_format: 'json', content: dataset.content }])
  await mount(page, 'app/chat/components/MessageResourcePreviews.vue', { props: { roomId: 'room', messageId: 'message' }, privileges: ['DOCUMENT_EDIT'] })
  const open = () => page.locator('.resource-preview-main').click()
  await open()
  const input = page.locator('textarea.code-editor')
  await expect(input).toHaveValue(dataset.content)
  await input.fill('{')
  await expect(page.getByText(/invalid JSON|JSON.*invalid/i)).toBeVisible()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await open()
  await expect(input).toHaveValue('{')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: testInfo.outputPath('data-document-dialog-mobile.png'), animations: 'disabled' })
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

test('a Dataset description saves independently of its JSON and retains its draft after a failed save', async ({ page }, testInfo) => {
  await fixtures(page)
  let current = { ...dataset, summary_content: null }
  let fail = true
  const writes = []
  await page.route(`**/api/datasets/${id}`, route => route.fulfill({ json: current }))
  await page.route(`**/api/datasets/${id}/content`, route => {
    const body = route.request().postDataJSON()
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Synthetic description save unavailable' } })
    writes.push(body)
    current = { ...current, summary_content: body.summary_content, lock_version: current.lock_version + 1 }
    return route.fulfill({ json: current })
  })
  await mount(page, 'app/dataset/components/DatasetDialog.vue', { props: { id }, privileges: ['DATASET_EDIT'] })
  await page.getByRole('tab', { name: 'Description and keywords', exact: true }).focus()
  await page.keyboard.press('Enter')
  const description = page.getByRole('textbox', { name: 'Description and keywords', exact: true })
  await expect(description).toHaveValue('')
  await description.fill('Synthetic amounts used for budget preparation.')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Synthetic description save unavailable')
  await expect(description).toHaveValue('Synthetic amounts used for budget preparation.')
  fail = false
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ content: dataset.content, expected_revision: 1,
    summary_content: 'Synthetic amounts used for budget preparation.' })
  await page.screenshot({ path: testInfo.outputPath('dataset-description-desktop.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(description).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('dataset-description-mobile.png'), animations: 'disabled' })
  await page.getByRole('tab', { name: 'Content', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'JSON content', exact: true })).toHaveValue('{\n  "amount": 0\n}')
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

for (const format of ['uri', 'url']) test(`a pasted Dataset ${format} converts to a card and opens the same modal after serialization`, async ({ page }) => {
  await fixtures(page)
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<p>Keep this</p>' }, privileges: ['DOCUMENT_ACCESS'] })
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
  await expect(page.getByRole('dialog').locator('.document-editor')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.evaluate(async content => window.testApp.mount({ component: 'core/util/components/RichText.vue', props: { content, profile: 'document' } }), saved)
  await page.getByRole('link', { name: dataset.title, exact: true }).click()
  await expect(page.getByRole('dialog').locator('.document-editor')).toBeVisible()
  expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/')
})
