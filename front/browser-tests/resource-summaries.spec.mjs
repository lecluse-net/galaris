import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

const dataset = {
  id: '00000000-0000-4000-8000-000000000564', uri: 'data://00000000-0000-4000-8000-000000000564',
  title: 'Synthetic reference data', content: '{"kept":true}', revision: 1, lock_version: 1,
  can_write: false, can_manage: false, can_delete: false, read_only: true,
  global_access: 0, group_access: 0, keywords: ['reference'], summary_content: 'Saved Dataset description.',
}

for (const kind of ['document', 'dataset']) test(`the ${kind} summary opens for a reader, retries, and refreshes on reopening`, async ({ page }, testInfo) => {
  let fail = true, calls = 0, content = 'Current resource purpose.'
  if (kind === 'document') {
    await jsonRoute(page, '**/api/agents?*', [agent])
    await jsonRoute(page, /\/api\/documents\/doc-a(?:\?.*)?$/, { item: { ...document, media_type: 'text/html', payload: { text: '<p>Original body.</p>' } }, agent_id: 7 })
    await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
    await jsonRoute(page, '**/api/documents/keywords?*', [])
    await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
    await page.route('**/api/documents/doc-a/summary?*', route => {
      calls++
      return fail ? route.fulfill({ status: 403, json: { detail: 'Synthetic denial' } })
        : route.fulfill({ json: { ...document, media_type: 'text/html', payload: { text: `<p>${content}</p>` }, keywords: ['reference'] } })
    })
    await mount(page, 'app/document/components/DocumentEditor.vue', {
      props: { documentId: document.id, agentId: 7, editable: false }, privileges: ['DOCUMENT_ACCESS'],
    })
  } else {
    await page.route(`**/api/datasets/${dataset.id}`, route => {
      if (calls === 0) { calls++; return route.fulfill({ json: dataset }) }
      calls++
      return fail ? route.fulfill({ status: 403, json: { detail: 'Synthetic denial' } })
        : route.fulfill({ json: { ...dataset, summary_content: content } })
    })
    await jsonRoute(page, `**/api/datasets/${dataset.id}/owner`, { owner: null, options: [] })
    await jsonRoute(page, `**/api/datasets/${dataset.id}/sharing`, { lock_version: 1, can_manage: false, grants: [], options: [], level: 'private' })
    await mount(page, 'app/dataset/components/DatasetDialog.vue', { props: { id: dataset.id }, privileges: ['DATASET_READ'] })
  }
  const button = page.getByRole('button', { name: 'View summary', exact: true })
  await button.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Summary', exact: true })
  await expect(dialog.getByRole('alert')).toContainText('Unable to load the summary.')
  fail = false
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByText(content, { exact: true })).toBeVisible()
  await expect(dialog.getByText('reference', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath(`${kind}-summary-desktop.png`), animations: 'disabled' })
  await dialog.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(dialog).toHaveCount(0)
  if (kind === 'dataset') await expect(page.getByRole('dialog')).toHaveCount(1)
  content = 'Updated saved description.'
  await button.click()
  await expect(dialog.getByText(content, { exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: testInfo.outputPath(`${kind}-summary-mobile.png`), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  content = ''
  await button.click()
  await expect(dialog.getByText('No summary is available for this resource.', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(dialog).toHaveCount(0)
})

test('a summary ignores late responses after its resource changes or the dialog closes', async ({ page }) => {
  await mount(page, 'core/util/components/ResourceSummaryButton.vue', { props: { resourceKey: 'source-a', title: 'Synthetic A' } })
  await page.evaluate(() => {
    window.summaryResolvers = []
    return window.testApp.setProps({ load: () => new Promise(resolve => window.summaryResolvers.push(resolve)) })
  })
  const button = page.getByRole('button', { name: 'View summary', exact: true })
  await button.click()
  await expect(page.getByRole('status')).toBeVisible()
  await page.evaluate(() => window.testApp.setProps({ resourceKey: 'source-b', title: 'Synthetic B' }))
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await button.click()
  await page.evaluate(() => window.summaryResolvers[1]({ content: 'Current B description', mediaType: 'text/plain', keywords: [] }))
  await expect(page.getByText('Current B description', { exact: true })).toBeVisible()
  await page.evaluate(() => window.summaryResolvers[0]({ content: 'Old A description', mediaType: 'text/plain', keywords: [] }))
  await expect(page.getByText('Old A description', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Current B description', { exact: true })).toBeVisible()
})
