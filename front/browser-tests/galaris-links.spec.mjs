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
const lastValue = page => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.value)
async function searchFixtures(page) {
  await jsonRoute(page, '**/api/processes/internal/resource-options?*', [])
  await jsonRoute(page, '**/api/agents**', [])
  await jsonRoute(page, '**/api/memory/documents/library', { entries: [] })
  await jsonRoute(page, '**/api/tasks/recent**', { items: [{ id: goalId, label: 'Project task', agent_id: 1 }] })
  await jsonRoute(page, '**/api/goals**', { items: [{ id: goalId, title: 'Project goal', agent_id: 1 }] })
}
async function openSearch(page) {
  if (!await page.getByRole('button', { name: 'Insert a link or file', exact: true }).first().isVisible()) {
    await page.getByRole('button', { name: 'Show more items', exact: true }).click()
  }
  await page.getByRole('button', { name: 'Insert a link or file', exact: true }).first().click()
  await page.getByRole('button', { name: 'Add an internal attachment', exact: true }).click()
  const search = page.getByRole('textbox', { name: 'Search accessible content', exact: true })
  await expect(search).toBeFocused()
  await search.fill('Project')
  await expect(page.getByText('Project goal', { exact: true })).toBeVisible()
}

test('heading and font-size commands change the authored document in normal and fullscreen editing', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: '<p>Document</p>', profile: 'document' } })
  const editable = page.locator('.ck-editor__editable')
  await expect(editable).toBeVisible()
  await editable.click()
  await page.getByRole('button', { name: 'Paragraph, Heading', exact: true }).click()
  await page.getByRole('menuitemradio', { name: 'Heading 1', exact: true }).click()
  await expect(editable.locator('h1')).toHaveText('Document')
  expect(await lastValue(page)).toContain('<h1>Document</h1>')
  await page.getByRole('button', { name: 'Enter fullscreen mode' }).click()
  await editable.click()
  await page.keyboard.press('Control+a')
  await page.getByRole('button', { name: 'Font Size', exact: true }).click()
  await page.getByRole('menuitemradio', { name: '24', exact: true }).click()
  expect(await lastValue(page)).toContain('font-size: 24px')
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(editable.locator('h1')).toHaveText('Document')
  expect(await lastValue(page)).not.toContain('font-size: 24px')
})

test('Galaris dialog filters targets and preserves selected formatting when inserting a canonical link', async ({ page }, testInfo) => {
  await searchFixtures(page)
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<p><strong>Selected text</strong></p>' } })
  await page.locator('.ck-editor__editable').click()
  await page.keyboard.press('Control+a')
  await openSearch(page)
  await expect(page.getByRole('button', { name: 'Insert link', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Goal', exact: true }).click()
  await expect(page.getByText('Project task', { exact: true })).toHaveCount(0)
  await page.getByText('Project goal', { exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Link text', exact: true })).toHaveValue('Selected text')
  await page.screenshot({ path: testInfo.outputPath('galaris-link-desktop.png') })
  await page.getByRole('button', { name: 'Insert link', exact: true }).click()
  await expect(page.locator('.ck-editor__editable a strong')).toHaveText('Selected text')
  expect(await lastValue(page)).toContain(`href="galaris://goal/${goalId}"`)
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(page.locator('.ck-editor__editable a')).toHaveCount(0)
  await expect(page.locator('.ck-editor__editable strong')).toHaveText('Selected text')
})

for (const mode of ['mobile', 'fullscreen']) test(`Galaris dialog works in dark ${mode} with an editable label`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: mode === 'mobile' ? 390 : 1440, height: 844 })
  await searchFixtures(page)
  await mount(page, 'core/util/components/RichTextEditor.vue', { dark: true, props: { profile: 'document', modelValue: '<p>Start </p>' } })
  if (mode === 'fullscreen') await page.getByRole('button', { name: 'Enter fullscreen mode' }).click()
  await page.locator('.ck-editor__editable').click()
  await page.keyboard.press('Control+End')
  await openSearch(page)
  await page.getByText('Project goal', { exact: true }).click()
  await page.getByRole('textbox', { name: 'Link text', exact: true }).fill('My goal')
  await page.screenshot({ path: testInfo.outputPath(`galaris-link-${mode}-dark.png`) })
  await page.getByRole('textbox', { name: 'Link text', exact: true }).press('Enter')
  await expect(page.locator('.ck-editor__editable a')).toHaveText('My goal')
  expect(await lastValue(page)).toContain(`href="galaris://goal/${goalId}"`)
})

test('Galaris dialog supports dismissal, retry and ignores stale search results', async ({ page }) => {
  await searchFixtures(page)
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile: 'document', modelValue: '<p>Unchanged</p>' } })
  await openSearch(page)
  await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
  await expect(page.locator('.galaris-link-dialog')).toHaveCount(0)
  expect(await lastValue(page)).toBeUndefined()
  await page.route(/\/api\/(agents|datasets|goals|tasks\/recent|processes\/internal\/resource-options)/, route => route.fulfill({ status: 503, json: { detail: 'Unavailable' } }))
  await page.getByRole('button', { name: 'Insert a link or file', exact: true }).first().click()
  await page.getByRole('button', { name: 'Add an internal attachment', exact: true }).click()
  const search = page.getByRole('textbox', { name: 'Search accessible content', exact: true })
  await search.fill('Project')
  await expect(page.getByRole('alert')).toContainText('Search is temporarily unavailable.')
  await page.unroute(/\/api\/(agents|datasets|goals|tasks\/recent|processes\/internal\/resource-options)/)
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('Project goal', { exact: true })).toBeVisible()
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/goals**', async route => {
    await pending
    await route.fulfill({ json: { items: [{ id: goalId, title: 'Stale goal', agent_id: 1 }] } })
  })
  await search.fill('Stale')
  await page.waitForRequest(request => request.url().includes('/api/goals'))
  await search.fill('x')
  release()
  await expect(page.getByText('Stale goal', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Insert link', exact: true })).toBeDisabled()
})
