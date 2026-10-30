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
  const dialog = page.getByRole(kind === 'document' ? 'region' : 'dialog', { name: 'Summary', exact: true })
  await expect(dialog.getByRole('alert')).toContainText('Unable to load the summary.')
  fail = false
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByText(content, { exact: true })).toBeVisible()
  if (kind === 'document') await expect(dialog.getByText('reference', { exact: true })).toHaveCount(0)
  else await expect(dialog.getByText('reference', { exact: true })).toBeVisible()
  if (kind === 'document') {
    await expect(dialog.getByRole('button', { name: 'Save summary', exact: true })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Regenerate summary', exact: true })).toHaveCount(0)
    await expect(page.getByText('Original body.', { exact: true })).toHaveCount(0)
  }
  await page.screenshot({ path: testInfo.outputPath(`${kind}-summary-desktop.png`), animations: 'disabled' })
  if (kind === 'document') await dialog.getByRole('button', { name: 'Back to document', exact: true }).click()
  else await dialog.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(dialog).toHaveCount(0)
  if (kind === 'dataset') await expect(page.getByRole('dialog')).toHaveCount(1)
  content = 'Updated saved description.'
  await button.click()
  await expect(dialog.getByText(content, { exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: testInfo.outputPath(`${kind}-summary-mobile.png`), animations: 'disabled' })
  if (kind === 'document') await dialog.getByRole('button', { name: 'Back to document', exact: true }).click()
  else await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  content = ''
  await button.click()
  await expect(dialog.getByText('No summary is available for this resource.', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: kind === 'document' ? 'Back to document' : 'Close', exact: true }).click()
  await expect(dialog).toHaveCount(0)
})

test('document summary editing preserves drafts on failure and regenerates without touching the document body', async ({ page }, testInfo) => {
  const source = { ...document, media_type: 'text/html', payload: { text: '<p>Original body.</p>' } }
  let summary = { ...source, payload: { text: '<p>Saved purpose.</p>' }, keywords: ['hidden-term'] }
  let failSave = true, conflict = false, forceCalls = 0
  const writes = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await page.route(/\/api\/documents\/doc-a(?:\?.*)?$/, route => route.fulfill({ json: { item: source, agent_id: 7 } }))
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/content-revisions?*', { items: [], total: 0, limit: 50, offset: 0, has_more: false })
  await page.route('**/api/documents/doc-a/summary?*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: summary })
    const values = route.request().postDataJSON()
    writes.push(values)
    if (failSave || conflict) return route.fulfill({ status: conflict ? 409 : 500, json: { detail: 'Synthetic save failure' } })
    summary = { ...summary, payload: values.payload, lock_version: summary.lock_version + 1 }
    source.lock_version = summary.lock_version
    return route.fulfill({ json: summary })
  })
  await page.route('**/api/documents/doc-a/summary/regenerate?*', async route => {
    forceCalls++
    expect(route.request().postDataJSON().expected_lock_version).toBe(summary.lock_version)
    summary = { ...summary, payload: { text: '<p>Forced fresh purpose.</p>' }, lock_version: summary.lock_version + 1 }
    source.lock_version = summary.lock_version
    await route.fulfill({ json: summary })
  })
  await mount(page, 'app/document/components/DocumentEditor.vue', {
    props: { documentId: document.id, agentId: 7 }, privileges: ['DOCUMENT_ACCESS', 'DOCUMENT_EDIT'],
  })
  const open = page.getByRole('button', { name: 'View summary', exact: true })
  const panel = page.getByRole('region', { name: 'Summary', exact: true })
  await open.click()
  const editor = panel.locator('[contenteditable="true"]')
  await editor.fill('Manually revised purpose.')
  await panel.getByRole('button', { name: 'Back to document', exact: true }).click()
  await expect(panel.getByRole('alert')).toContainText('Unable to save the summary.')
  await expect(editor).toContainText('Manually revised purpose.')
  failSave = false
  await panel.getByRole('button', { name: 'Save summary', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Save summary', exact: true })).toBeDisabled()
  expect(writes.at(-1)).toEqual({ payload: { text: '<p>Manually revised purpose.</p>' }, expected_lock_version: 3 })
  await panel.getByRole('button', { name: 'Regenerate summary', exact: true }).click()
  const confirmation = page.getByRole('dialog', { name: 'Regenerate summary', exact: true })
  await expect(confirmation).toContainText('Regeneration replaces the summary, including your manual edits.')
  expect(forceCalls).toBe(0)
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(confirmation).toHaveCount(0)
  await expect(editor).toContainText('Manually revised purpose.')
  await panel.getByRole('button', { name: 'Regenerate summary', exact: true }).click()
  await confirmation.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(confirmation).toHaveCount(0)
  expect(forceCalls).toBe(0)
  await panel.getByRole('button', { name: 'Regenerate summary', exact: true }).click()
  await confirmation.getByRole('button', { name: 'Regenerate summary', exact: true }).click()
  await expect(panel.getByText('Forced fresh purpose.', { exact: true })).toBeVisible()
  expect(forceCalls).toBe(1)
  await expect(panel.getByText('hidden-term', { exact: true })).toHaveCount(0)
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('document-summary-edit-dark.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  for (const name of ['Regenerate summary', 'Save summary', 'Back to document']) {
    await expect(panel.getByRole('button', { name, exact: true })).toBeInViewport({ ratio: 1 })
  }
  await testInfo.attach('summary-actions-layout', {
    body: JSON.stringify(await panel.locator('header button').evaluateAll(buttons => buttons.map(button => ({
      label: button.getAttribute('aria-label') || button.textContent, rect: button.getBoundingClientRect().toJSON(),
      display: getComputedStyle(button).display, color: getComputedStyle(button).color,
    }))), null, 2), contentType: 'application/json',
  })
  await page.screenshot({ path: testInfo.outputPath('document-summary-edit-mobile.png'), animations: 'disabled' })
  await panel.getByRole('button', { name: 'Back to document', exact: true }).click()
  await expect(page.getByText('Original body.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Open content history', exact: true }).click()
  await expect(page.getByText('No content version is available.', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('document-history-mobile.png'), animations: 'disabled' })
  await page.getByRole('button', { name: 'Back to document', exact: true }).click()
  await expect(page.getByText('Original body.', { exact: true })).toBeVisible()
  await open.click()
  await expect(panel.getByText('Forced fresh purpose.', { exact: true })).toBeVisible()
  await panel.locator('[contenteditable="true"]').fill('Keep this conflicting draft.')
  conflict = true
  await panel.getByRole('button', { name: 'Save summary', exact: true }).click()
  await expect(panel.getByRole('alert')).toContainText('The document or summary changed.')
  await expect(panel.locator('[contenteditable="true"]')).toContainText('Keep this conflicting draft.')
  expect(source.payload.text).toBe('<p>Original body.</p>')
})

test('the document summary ignores a late response after changing documents', async ({ page }) => {
  let release
  await page.route('**/api/documents/first/summary?*', async route => {
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: { ...document, payload: { text: '<p>Late first summary.</p>' } } }).catch(() => {})
  })
  await jsonRoute(page, '**/api/documents/second/summary?*', { ...document, id: 'second', payload: { text: '<p>Current second summary.</p>' } })
  await mount(page, 'app/document/components/DocumentSummaryPanel.vue', {
    props: { documentId: 'first', agentId: 7, editable: false, minHeight: '240px' },
  })
  await expect.poll(() => !!release).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ documentId: 'second' }))
  await expect(page.getByText('Current second summary.', { exact: true })).toBeVisible()
  release()
  await expect(page.getByText('Late first summary.', { exact: true })).toHaveCount(0)
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
