import { test, expect, mount, jsonRoute, editorHtml } from './fixtures.mjs'

const id = '11111111-1111-4111-8111-111111111111'
const sources = [`chat://chat:direct:7:1:synthetic/${id}`, 'console://exports/report.txt',
  `file://${id}`, 'nextcloud://Shared/Report%20%C3%A9t%C3%A9.txt', 'custom-provider://folder/report.txt',
  `data://${id}/attachments/${id}`, 'galaris://skill/synthetic-guide/SKILL.md', `galaris://goal/${id}/cycles/`]

test('Markdown readers and legacy editing retain canonical source references', async ({ page }) => {
  const content = sources.map((uri, i) => `[Source ${i}](${uri})`).join('\n\n')
  await mount(page, 'core/util/components/Markdown.vue', { props: { content } })
  for (const [i, uri] of sources.entries()) {
    await expect(page.getByRole('link', { name: `Source ${i}`, exact: true })).toHaveAttribute('href', '/files?uri=' + encodeURIComponent(uri))
  }
  const saved = await page.evaluate(async content => {
    const { markdownToHtml, htmlToMarkdown } = await import('/core/util/markdownWysiwyg.ts')
    return htmlToMarkdown(markdownToHtml(content))
  }, content)
  for (const uri of sources) expect(saved).toContain(`](${uri})`)
})

for (const profile of ['rich-text', 'document']) test(`all resource schemes survive editing and reopen as application links (${profile})`, async ({ page }) => {
  const html = '<p>Sources</p>' + sources.map((uri, i) => `<p><a href="${uri}">Source ${i}</a></p>`).join('')
  await mount(page, 'core/util/components/RichTextEditor.vue', { props: { profile, modelValue: html } })
  const editor = page.locator('[data-editor-surface]')
  await editor.locator('p').first().click()
  await page.keyboard.press('End')
  await page.keyboard.type(' retained')
  const saved = await editorHtml(page)
  for (const uri of sources) expect(saved).toContain(`href="${uri}"`)
  expect(saved).not.toContain('/files?uri=')
  await page.evaluate(({ saved, profile }) => window.testApp.mount({
    component: 'core/util/components/RichText.vue', props: { profile, content: saved },
  }), { saved, profile })
  for (const [i, uri] of sources.entries()) {
    await expect(page.getByRole('link', { name: `Source ${i}`, exact: true })).toHaveAttribute('href', '/files?uri=' + encodeURIComponent(uri))
  }
  // Malformed and executable references still cannot become browser links.
  await page.evaluate(() => window.testApp.setProps({ content: '<p><a href="javascript://alert(1)">Unsafe</a><a href="file:///etc/passwd">Local path</a></p>' }))
  await expect(page.locator('.rich-content a[href]')).toHaveCount(0)
})

for (const [width, dark] of [[1440, false], [390, true]]) test(`resource citation survives agent selection, denial, retry and reopening (${width}px)`, async ({ page, context }, testInfo) => {
  const uri = sources[0]
  await page.setViewportSize({ width, height: 900 })
  await mount(page, 'core/util/components/RichText.vue', { props: { content: `<p><a href="${uri}">Original agreement</a></p>` } })
  const link = page.getByRole('link', { name: 'Original agreement', exact: true })
  const href = await link.getAttribute('href')
  expect(new URL(href, 'http://example.invalid').searchParams.get('uri')).toBe(uri)
  // Follow the real hyperlink with the keyboard. Freeze only the destination
  // document; the real Files route and its controls are exercised below.
  await context.route('**/files?uri=*', route => route.fulfill({ contentType: 'text/html', body: '<p>Synthetic navigation target</p>' }))
  const opened = page.waitForEvent('popup')
  await link.focus()
  await link.press('Enter')
  const destination = await opened
  await expect(destination).toHaveURL(url => url.pathname === '/files' && url.searchParams.get('uri') === uri)
  await destination.close()

  const entry = { uri, name: 'Agreement.txt', is_collection: false, media_type: 'text/plain', size: 24, capabilities: ['info', 'read'] }
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'chat', label: 'Chat', capabilities: ['info', 'read'], native: false, root_listable: false }])
  await page.route('**/api/file-share/browser/entries?*', route => route.fulfill({ json: {
    uri: new URL(route.request().url()).searchParams.get('uri'), entries: [entry], next_cursor: null, truncated: false,
  } }))
  let denied = true, reads = 0, inspections = 0
  await page.route('**/api/file-share/browser/info?*', route => {
    inspections++
    const query = new URL(route.request().url()).searchParams
    expect(query.get('uri')).toBe(uri)
    expect(query.get('agent_id')).toBe('7')
    return route.fulfill(denied ? { status: 403, json: { detail: 'Synthetic access denial' } } : { json: entry })
  })
  await page.route('**/api/file-share/browser/content?*', route => {
    reads++
    expect(new URL(route.request().url()).searchParams.get('uri')).toBe(uri)
    return route.fulfill({ contentType: 'text/plain', body: 'Synthetic original agreement' })
  })
  await page.route('**/api/file-share/browser/thumbnail?*', route => route.fulfill({ status: 204 }))
  await mount(page, 'test-support/browser/FileRouteHarness.vue', { route: href, browserHistory: true, dark, privileges: ['FILE_ACCESS'] })
  expect(reads).toBe(0)
  await page.getByRole('button', { name: 'Browse files for Alice Example', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  expect(reads).toBe(0)
  denied = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('Synthetic original agreement', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('resource-source.png') })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  denied = true
  await page.getByRole('button', { name: 'Open Agreement.txt', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(dialog).toHaveCount(0)
  expect(inspections).toBe(3)
  denied = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByText('Synthetic original agreement', { exact: true })).toBeVisible()
  expect(inspections).toBe(4)
  // The same preview bytes may be reused only after the new ACL check succeeds.
  expect(reads).toBeGreaterThanOrEqual(1)
})
