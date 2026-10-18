import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'

const processUri = 'galaris://processes/synthetic_process'
const runId = '11111111-1111-4111-8111-111111111111'
const runUri = `galaris://processes/runs/${runId}`
const graph = { schema_version: 'galaris.bpmn/v1', input_schema: {}, output_schema: {}, files: {}, actors: [], nodes: [
  { id: 'start', kind: 'start', title: 'Start', config: {}, x: 0, y: 0, body: null },
  { id: 'work', kind: 'task', title: 'Synthetic review', config: { prompt: 'Review this invented example.' }, x: 0, y: 0, body: null },
  { id: 'end', kind: 'end', title: 'End', config: {}, x: 0, y: 0, body: null },
], flows: [{ id: 'one', source: 'start', target: 'work' }, { id: 'two', source: 'work', target: 'end' }] }
const preview = uri => ({ uri, kind: uri === processUri ? 'process' : 'process_run', id: uri === processUri ? 'synthetic_process' : runId,
  title: 'Synthetic process', description: 'An entirely invented workflow.', revision: 1, graph, process_uri: processUri })
async function previewRoute(page) {
  await page.route('**/api/processes/internal/resource-preview?*', route => route.fulfill({ json: preview(new URL(route.request().url()).searchParams.get('uri')) }))
}

test('file previews open a read-only Process modal and a Run modal with their diagram miniatures', async ({ page }) => {
  await previewRoute(page)
  await jsonRoute(page, '**/api/agents/selection?*', [{ id: 7, label: 'Alice Example', has_avatar: false }])
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'galaris', label: 'Galaris', capabilities: ['list', 'read'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', { uri: 'galaris://', entries: [processUri, runUri].map((uri, index) => ({
    uri, name: index ? 'Synthetic execution' : 'Synthetic process', media_type: 'application/json', size: null,
    is_collection: false, capabilities: ['read', 'info'], metadata: { tool_code: 'galaris' },
  })), next_cursor: null, truncated: false })
  await jsonRoute(page, `**/api/processes/internal/runs/${runId}?*`, { id: runId, status: 'success', graph, nodes: [], total: 0,
    page: 1, page_size: 50, events: [], event_cursor: 0, breakpoints: [], node_statuses: {}, can_control: false, paused: false,
    data: {}, files: [], data_revision: 1, data_uri: runUri + '/data', attachments_uri: runUri + '/attachments/' })
  await jsonRoute(page, `**/api/processes/internal/runs/${runId}/metrics*`, { direct: {}, inclusive: {}, tasks: {}, nodes: {}, partial: false })
  await mount(page, 'app/file_share/pages/index.vue', { privileges: ['MEMORY_ACCESS', 'PROCESS_READ'] })
  await page.getByRole('button', { name: 'Browse files for Alice Example', exact: true }).click()
  await page.getByText('Galaris', { exact: true }).click()
  await expect(page.locator('.process-thumbnail svg')).toHaveCount(2)
  await expect(page.locator('.process-thumbnail-run')).toHaveCount(1)
  await page.locator('.file-main').getByRole('button', { name: 'Open Synthetic process', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Read-only access', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
  await page.getByRole('dialog').getByRole('button', { name: 'Synthetic review · work', exact: true }).click()
  await expect(page.getByText('Review this invented example.', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.locator('.file-main').getByRole('button', { name: 'Open Synthetic execution', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('link', { name: `Copy run URL: ${runId}`, exact: true })).toHaveAttribute('href', runUri)
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
})

for (const width of [1440, 390]) test(`document diagram citations preserve their URI and expose zoom and the full preview at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  await previewRoute(page)
  const html = `<p>Process guide.</p><blockquote class="galaris-link-card galaris-process-diagram"><p><a href="${processUri}">Synthetic process</a></p></blockquote><p>Closing note.</p>`
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { modelValue: html, profile: 'document' }, privileges: ['MEMORY_ACCESS', 'PROCESS_READ'] })
  const inline = page.locator('.process-preview--inline')
  await expect(inline.getByRole('button', { name: 'Synthetic review · work', exact: true })).toBeVisible()
  await inline.hover()
  await inline.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await inline.getByRole('button', { name: 'Fit the diagram', exact: true }).click()
  await inline.getByRole('button', { name: 'Open preview', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('Read-only access', { exact: true })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.locator('[data-editor-surface]').click({ position: { x: 15, y: 15 } })
  await page.keyboard.press('Control+End'); await page.keyboard.type(' Added text.')
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1)?.args[0] ?? '')).toContain('Added text.')
  const saved = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'update:modelValue').at(-1).args[0])
  expect(saved).toContain('galaris-process-diagram'); expect(saved).toContain(processUri)
  expect(saved).not.toContain('<svg'); expect(saved).not.toContain('process-preview')
  await page.screenshot({ path: testInfo.outputPath('document-process-diagram.png'), fullPage: true })
  await page.evaluate(modelValue => window.testApp.setProps({ modelValue, readonly: true }), saved)
  await expect(inline.getByRole('button', { name: 'Synthetic review · work', exact: true })).toBeVisible()
})

test('the internal picker inserts Process and Run title links without attachment membership', async ({ page }) => {
  await previewRoute(page)
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'galaris', label: 'Galaris', capabilities: ['list'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', { entries: [processUri, runUri].map(uri => ({ uri, name: uri === processUri ? 'Synthetic process' : 'Synthetic execution', is_collection: false, media_type: 'application/json', size: null, capabilities: ['read'], metadata: { tool_code: 'galaris' } })), truncated: false, next_cursor: null })
  await mount(page, 'documentResourceReferences.vue', { props: { documentId: 'synthetic-document', agentId: 7, editable: true, pickerOpen: true } })
  const dialog = page.getByRole('dialog')
  await dialog.getByText('Galaris', { exact: true }).click()
  await dialog.getByRole('button', { name: 'Select Synthetic process', exact: true }).click()
  await dialog.getByRole('button', { name: 'Select Synthetic execution', exact: true }).click()
  await dialog.getByRole('button', { name: 'Select', exact: true }).click()
  const html = await page.evaluate(() => window.testApp.events.filter(event => event.name === 'picked' && event.args[0]).at(-1).args[0])
  expect(html).toContain(`href="${processUri}"`)
  expect(html).toContain(`href="${runUri}"`)
  expect(html).not.toContain('blockquote')
  await expect(page.locator('.resource-preview-card')).toHaveCount(0)
})

test('a Process citation switches between title link and diagram without saving the live canvas', async ({ page }) => {
  await previewRoute(page)
  await mount(page, 'core/util/components/RichTextEditor.vue')
  await page.evaluate(async uri => {
    const { processReferenceHtml } = await import('/app/process/contracts.ts')
    await window.testApp.mount({ component: 'core/util/components/RichTextEditor.vue', props: {
      profile: 'document', modelValue: processReferenceHtml(uri, 'Synthetic process', false),
      createLinkCard: async value => processReferenceHtml(value, 'Synthetic process', true),
    } })
  }, processUri)
  const editor = page.locator('[data-editor-surface]')
  await editor.getByRole('link', { name: 'Synthetic process', exact: true }).click()
  await page.getByRole('button', { name: 'Show card', exact: true }).click()
  await expect(editor.locator('.process-preview--inline')).toHaveCount(1)
  await editor.locator('blockquote > p a').click()
  await page.keyboard.press('Alt+Enter')
  await expect(page.getByRole('dialog').getByText('Read-only access', { exact: true })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: 'Show URL', exact: true }).click()
  await expect(editor.locator('.process-preview--inline')).toHaveCount(0)
  await expect(editor.getByRole('link', { name: 'Synthetic process', exact: true })).toHaveAttribute('data-rich-reference', processUri)
  await editor.getByRole('link', { name: 'Synthetic process', exact: true }).click()
  await page.getByRole('button', { name: 'Show card', exact: true }).click()
  await expect(editor.locator('.process-preview--inline')).toHaveCount(1)
  const source = await editorHtml(page)
  expect(source).toContain(processUri); expect(source).toContain('Synthetic process')
  expect(source).toContain('galaris-process-diagram'); expect(source).not.toContain('<svg')
})
