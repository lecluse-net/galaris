import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const folder = { uri: 'mail://b_SU5CT1g/', name: 'INBOX', is_collection: true, media_type: 'inode/directory', size: null, capabilities: ['info', 'list'] }
const item = ref => ({ uri: `${folder.uri}message-${ref}.eml`, name: `${ref}.eml`, is_collection: false,
  media_type: 'message/rfc822', size: null, modified_at: '2026-01-02T12:30:00Z', capabilities: ['info', 'read', 'copy'],
  metadata: { mail_message_ref: ref, subject: `Subject ${ref}`, from_name: 'Example sender', from_address: 'sender@example.test', seen: false, has_attachments: true } })
const listing = (uri, entries) => ({ uri, entries, truncated: false, next_cursor: null, ancestors: uri === folder.uri ? [
  { ...folder, uri: 'mail://', name: 'Mail' }, folder,
] : [] })
const detail = ref => ({ ref, subject: `Subject ${ref}`, from_name: 'Example sender', from_address: 'sender@example.test',
  to_addresses: ['reader@example.test'], cc_addresses: [], date: '2026-01-02T12:30:00Z', seen: false, flagged: false,
  body: 'Synthetic first page <img src="https://example.test/tracker" onerror="window.syntheticMailExecuted = true">',
  body_start: 0, body_end: 120, body_total: 140, next_body_offset: 120,
  attachments: [{ uri: 'mail://attachment/m1_example/part-2/example.txt', filename: 'example.txt', media_type: 'text/plain', size: 20, part_id: 'part-2' }] })

for (const width of [1440, 390]) test(`IMAP mail opens folders, pages, attachments and retries without executing content at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'mail', label: 'Mail', capabilities: ['info', 'list', 'read'], native: false }])
  await page.route('**/api/file-share/browser/entries?*', route => {
    const uri = new URL(route.request().url()).searchParams.get('uri')
    return route.fulfill({ json: listing(uri, uri === 'mail://' ? [folder] : [item('m1_first'), item('m1_second')]) })
  })
  let failBody = true
  await page.route('**/api/mail/browser/message?*', route => {
    const params = new URL(route.request().url()).searchParams
    const ref = params.get('message_ref')
    if (params.get('body_offset') === '120') {
      if (failBody) { failBody = false; return route.fulfill({ status: 502 }) }
      return route.fulfill({ json: { ...detail(ref), body: 'Synthetic last page', body_start: 120, body_end: 140, next_body_offset: null } })
    }
    return route.fulfill({ json: detail(ref) })
  })
  await page.route('**/api/file-share/browser/content?*', route => route.fulfill({ contentType: 'text/plain', body: 'Synthetic attachment' }))
  await mount(page, 'test-support/browser/FileRouteHarness.vue', { route: '/files?agent_id=7', browserHistory: true, privileges: ['FILE_ACCESS', 'MAIL_ACCESS'] })
  await page.getByRole('button', { name: 'Open Mail', exact: true }).click()
  await page.getByRole('button', { name: 'Open INBOX', exact: true }).click()
  await expect(page.getByRole('navigation', { name: 'File navigation' })).toContainText('INBOX')
  const first = page.getByLabel('Open m1_first.eml', { exact: true })
  await first.focus()
  await page.keyboard.press('Enter')
  let dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('reader@example.test')
  await expect(dialog).toContainText(detail('m1_first').body)
  expect(await page.evaluate(() => window.syntheticMailExecuted)).toBeUndefined()
  await dialog.getByRole('button', { name: 'Read more', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Unable to read this email')
  await expect(dialog).toContainText('Synthetic first page')
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog).toContainText('Synthetic last page')
  await expect(dialog.getByRole('button', { name: 'Read more', exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('mail-reader-light.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('mail-reader-dark.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Open preview of example.txt', exact: true }).click()
  await expect(page.getByText('Synthetic attachment', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Open preview of example.txt', exact: true })).toHaveCount(0)
  await expect(dialog).toContainText('Synthetic last page')
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await first.click()
  dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Synthetic first page')
  await expect(dialog).not.toContainText('Synthetic last page')
  // Backdrop dismissal is a shared modal guarantee, including this new reader.
  await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 }, force: true })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByLabel('Open m1_second.eml', { exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Subject m1_second')
})

test('closing the mail reader discards a late body response before another message opens', async ({ page }) => {
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'mail', label: 'Mail', capabilities: ['list'], native: false }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', listing(folder.uri, [item('m1_first'), item('m1_second')]))
  let release
  const delayed = new Promise(resolve => { release = resolve })
  await page.route('**/api/mail/browser/message?*', async route => {
    const ref = new URL(route.request().url()).searchParams.get('message_ref')
    if (ref === 'm1_first') await delayed
    await route.fulfill({ json: detail(ref) }).catch(() => {})
  })
  await mount(page, 'test-support/browser/FileRouteHarness.vue', { route: `/files?agent_id=7&uri=${encodeURIComponent(folder.uri)}`, browserHistory: true, privileges: ['FILE_ACCESS', 'MAIL_ACCESS'] })
  const started = page.waitForRequest(request => request.url().includes('/mail/browser/message?'))
  await page.getByLabel('Open m1_first.eml', { exact: true }).click()
  await started
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByLabel('Open m1_second.eml', { exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Subject m1_second')
  release()
  await expect(page.getByRole('dialog')).not.toContainText('Subject m1_first')
})

test('mail remains selectable and refreshable after its preview closes in the file picker', async ({ page }) => {
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'mail', label: 'Mail', capabilities: ['list'], native: false }])
  let listings = 0
  await page.route('**/api/file-share/browser/entries?*', route => {
    listings++
    const uri = new URL(route.request().url()).searchParams.get('uri')
    return route.fulfill({ json: listing(uri, uri === 'mail://' ? [folder] : [item('m1_first')]) })
  })
  await jsonRoute(page, '**/api/mail/browser/message?*', { ...detail('m1_first'), attachments: [] })
  await mount(page, 'resourcePicker.vue', { props: { modelValue: true, agentId: 7 }, privileges: ['FILE_ACCESS', 'MAIL_ACCESS'] })
  await page.getByRole('button', { name: 'Open Mail', exact: true }).click()
  await page.getByRole('button', { name: 'Open INBOX', exact: true }).click()
  await page.getByRole('button', { name: 'Preview m1_first.eml', exact: true }).click()
  const reader = page.getByRole('dialog', { name: 'Subject m1_first', exact: true })
  await expect(reader).toContainText('Synthetic first page')
  await reader.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await page.getByRole('checkbox', { name: 'Select m1_first.eml', exact: true }).check()
  await expect(page.getByLabel('Selected files', { exact: true })).toContainText('m1_first.eml')
  const previous = listings
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect.poll(() => listings).toBeGreaterThan(previous)
  await expect(page.getByRole('checkbox', { name: 'Select m1_first.eml', exact: true })).toBeChecked()
})
