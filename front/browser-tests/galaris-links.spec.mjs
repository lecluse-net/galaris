import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { result } from './data.mjs'

for (const mode of ['read', 'edit']) test(`a Task citation opens its modal without navigation in ${mode} mode`, async ({ page }) => {
  const id = '00000000-0000-0000-0000-000000000003'
  const task = { id, label: 'Synthetic cited task', objective: '<p>Synthetic task objective</p>', status: 'SUCCESS', paused: false, agent_id: null, parent_id: null, topic_id: null, data: {}, execution_result: result, revision: 1, created_at: '2026-09-01T12:00:00Z', updated_at: null, effort: 'standard', ai: true, cost: 0, messages: [] }
  await jsonRoute(page, `**/api/tasks/${id}/full`, task)
  await jsonRoute(page, `**/api/tasks/${id}`, task)
  await jsonRoute(page, `**/api/tasks/${id}/children`, [])
  await jsonRoute(page, `**/api/tasks/${id}/budget`, { enabled: false })
  await jsonRoute(page, '**/api/tasks/activity', [])
  const html = `<p><a href="galaris://task/${id}">Synthetic cited task</a></p>`
  await mount(page, `core/util/components/${mode === 'edit' ? 'RichTextEditor' : 'RichText'}.vue`, { props: mode === 'edit' ? { modelValue: html, profile: 'document' } : { content: html, profile: 'document' }, privileges: ['TASK_ACCESS'] })
  const url = page.url(), popups = []
  page.on('popup', popup => popups.push(popup))
  const open = async () => {
    await page.getByRole('link', { name: 'Synthetic cited task', exact: true }).click()
    if (mode === 'edit') await page.keyboard.press('Alt+Enter')
    await expect(page.getByRole('dialog').locator('.task-detail')).toContainText('Synthetic task objective')
    expect(page.url()).toBe(url); expect(popups).toHaveLength(0)
  }
  await open()
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await open()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

const goalId = '00000000-0000-0000-0000-000000000123'
const lastValue = page => page.evaluate(() => {
  const event = window.testApp.events.filter(event => ['update:modelValue', 'update:draft'].includes(event.name)).at(-1)
  return event?.name === 'update:draft' ? event.value.content : event?.value
})
async function pickerFixtures(page) {
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'galaris', label: 'Galaris', capabilities: ['list'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', { entries: [{ uri: `galaris://goal/${goalId}`, name: 'Synthetic goal', is_collection: false, media_type: 'text/html', size: null, capabilities: ['read'], metadata: { tool_code: 'galaris' } }], next_cursor: null, truncated: false })
  await page.route('**/api/file-share/browser/thumbnail?*', route => route.fulfill({ status: 404 }))
}
async function openPicker(page, width = 1440) {
  await page.getByRole('button', { name: 'Galaris link', exact: true }).click()
  const picker = page.getByRole('dialog').filter({ has: page.getByText('Add an internal attachment', { exact: true }) })
  await expect(picker).toBeVisible()
  if (width < 1024) await picker.getByRole('button', { name: 'Show locations', exact: true }).click()
  await picker.getByText('Galaris', { exact: true }).click()
  return picker
}

test('heading and font-size commands change the authored document in normal and fullscreen editing', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<p>Document</p>', profile: 'document' } })
  const editable = page.locator('[data-editor-surface]')
  await expect(editable).toBeVisible()
  await editable.click()
  await page.getByRole('button', { name: 'Style', exact: true }).click()
  await page.getByRole('menuitemradio', { name: 'Heading 1', exact: true }).click()
  await expect(editable.locator('h1')).toHaveText('Document')
  expect(await lastValue(page)).toContain('<h1>Document</h1>')
  await page.getByRole('button', { name: 'Fullscreen' }).click()
  await editable.click()
  await page.keyboard.press('Control+a')
  await page.getByRole('button', { name: 'Font size', exact: true }).click()
  await page.getByRole('menuitemradio', { name: '24', exact: true }).click()
  expect(await lastValue(page)).toContain('font-size: 24px')
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(editable.locator('h1')).toHaveText('Document')
  expect(await lastValue(page)).not.toContain('font-size: 24px')
})

for (const mode of ['document', 'simple', 'mobile', 'fullscreen']) test(`the internal picker preserves selected formatting in ${mode} editing`, async ({ page }, testInfo) => {
  const width = mode === 'mobile' ? 390 : 1440
  await page.setViewportSize({ width, height: 900 })
  await pickerFixtures(page)
  if (mode === 'simple') await mount(page, 'app/memory/components/MemoryItemForm.vue', { props: {
    draft: { content: '<p><strong>Selected text</strong></p>', nodeKind: 'memory', mediaType: 'text/html', contentType: 'text', keywords: [], revision: 1 },
    editingId: null, sharingEditable: false,
  } })
  else await mount(page, 'core/util/components/RichTextEditor.vue', { dark: mode === 'mobile' || mode === 'fullscreen', props: {
    profile: mode === 'document' ? 'document' : 'rich-text', singleRowToolbar: mode === 'simple',
    hiddenToolbarGroups: mode === 'simple' ? ['reading', 'editing'] : [], modelValue: '<p><strong>Selected text</strong></p>',
  } })
  if (mode === 'fullscreen') await page.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  await page.locator('[data-editor-surface]').click()
  await page.keyboard.press('Control+a')
  const picker = await openPicker(page, width)
  await expect(picker.getByRole('button', { name: 'Select', exact: true })).toBeDisabled()
  await picker.getByRole('button', { name: 'Select Synthetic goal', exact: true }).click()
  await page.screenshot({ path: testInfo.outputPath('internal-reference-picker.png'), animations: 'disabled' })
  await picker.getByRole('button', { name: 'Select', exact: true }).click()
  await expect(page.locator('[data-editor-surface] a strong')).toHaveText('Selected text')
  expect(await lastValue(page)).toContain(`href="galaris://goal/${goalId}"`)
  await page.keyboard.press('Control+z')
  await expect(page.locator('[data-editor-surface] a')).toHaveCount(0)
  await expect(page.locator('[data-editor-surface] strong')).toHaveText('Selected text')
})

test('the internal picker supports dismissal, retry and discards a selection after the content changes', async ({ page }) => {
  await pickerFixtures(page)
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<p>Unchanged</p>', singleRowToolbar: true } })
  await openPicker(page)
  await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await lastValue(page)).toBeUndefined()
  await page.route('**/api/file-share/browser/schemes?*', route => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }))
  await page.getByRole('button', { name: 'Galaris link', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.unroute('**/api/file-share/browser/schemes?*')
  await pickerFixtures(page)
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await page.getByRole('dialog').getByText('Galaris', { exact: true }).click()
  await page.getByRole('button', { name: 'Select Synthetic goal', exact: true }).click()
  await page.evaluate(() => window.testApp.setProps({ modelValue: '<p>Replacement content</p>' }))
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('[data-editor-surface]')).toHaveText('Replacement content')
  expect(await lastValue(page)).toBeUndefined()
  await openPicker(page)
  await page.getByRole('button', { name: 'Select Synthetic goal', exact: true }).click()
  await page.getByRole('button', { name: 'Select', exact: true }).click()
  await expect(page.locator('[data-editor-surface] a')).toHaveText('Synthetic goal')
})
