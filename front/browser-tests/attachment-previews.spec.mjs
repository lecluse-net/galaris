import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const markdown = '# Project notes\n\nA **formatted** attachment.\n\n- First item\n- Second item\n\n| Name | Status |\n| --- | --- |\n| Preview | Ready |\n\n```js\nconst ready = true\n```\n\n<script>window.markdownExecuted = true</script>'

async function setup(page, surface, { name = 'NOTES.MD', mime = 'application/octet-stream', respond } = {}) {
  const file = { id: 'file-1', uri: 'chat://room-1/file-1', name, mime_type: mime, media_type: mime, kind: 'file', size_bytes: markdown.length }
  const contentRoute = surface === 'document'
    ? '**/api/memory/documents/*/attachments/file-1?*'
    : surface === 'resource' ? '**/api/chat/rooms/*/messages/message-1/previews/content?*' : '**/api/chat/rooms/*/files/file-1*'
  await page.route(contentRoute, respond ?? (route => route.fulfill({ contentType: mime, body: markdown })))
  await page.route('**/api/memory/documents/*/attachments/*/thumbnail?*', route => route.fulfill({ status: 204 }))
  await jsonRoute(page, /\/previews(?:\?.*)?$/, [{ uri: file.uri, kind: 'file', title: name, subtitle: '', description: '', media_type: mime, content: 'Truncated preview', content_format: 'text', truncated: true, image_available: false, download_available: true, open_mode: 'inline', external_url: null, embed_url: null, metadata: {} }])
  await jsonRoute(page, '**/api/chat/rooms/*/speech/status*', { available_agent_ids: [] })
  const component = surface === 'document' ? 'app/memory/components/DocumentAttachments.vue' : `app/chat/components/${surface === 'message' ? 'MessageTimeline' : 'MessageResourcePreviews'}.vue`
  const props = surface === 'document'
    ? { documentId: 'document-1', agentId: 7, attachments: [file] }
    : surface === 'resource' ? { roomId: 'room-1', messageId: 'message-1' }
    : { roomId: 'room-1', agentId: 7, agentName: 'Test', activity: [], liveRound: null, messages: [{ id: 'message-1', external_id: 'external-1', text: '', files: [file], is_mine: true, sender: { display_name: 'Test', is_ai: false }, created_at: '2026-01-01T12:00:00Z' }] }
  await mount(page, component, { props })
  const open = surface === 'message' ? page.getByRole('button', { name, exact: true }) : page.locator('.resource-preview-main')
  return { open, dialog: page.getByRole('dialog'), props }
}

for (const surface of ['document', 'message', 'resource']) {
  for (const source of ['extension', 'mime']) {
    test(`${surface} Markdown attachment renders, downloads and reopens by ${source}`, async ({ page }) => {
      const { open, dialog } = await setup(page, surface, source === 'mime' ? { name: 'notes.txt', mime: 'text/markdown; charset=utf-8' } : {})
      if (surface === 'message') await expect(page.getByRole('heading', { name: 'Project notes' })).toBeVisible()
      await open.click()
      await expect(dialog.getByRole('heading', { name: 'Project notes' })).toBeVisible()
      await expect(dialog.locator('strong')).toHaveText('formatted')
      await expect(dialog.getByRole('listitem')).toHaveText(['First item', 'Second item'])
      await expect(dialog.getByRole('cell', { name: 'Ready', exact: true })).toBeVisible()
      await expect(dialog.locator('pre code')).toContainText('const ready = true')
      expect(await page.evaluate(() => window.markdownExecuted)).toBeUndefined()
      await expect(dialog.locator('script')).toHaveCount(0)
      const downloaded = page.waitForEvent('download')
      await dialog.getByRole('button', { name: /Download/ }).click()
      expect((await downloaded).suggestedFilename()).toBe(source === 'mime' ? 'notes.txt' : 'NOTES.MD')
      await dialog.getByRole('button', { name: 'Enter fullscreen', exact: true }).click()
      await expect.poll(() => page.evaluate(() => document.fullscreenElement !== null)).toBe(true)
      await dialog.getByRole('button', { name: 'Exit fullscreen', exact: true }).click()
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dialog).toHaveCount(0)
      await page.setViewportSize({ width: 390, height: 844 })
      await open.click()
      await expect(dialog.getByRole('heading', { name: 'Project notes' })).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
    })
  }
  for (const [name, mime, content, token] of [
    ['notes.txt', 'text/plain', 'Plain text\n  Preserve indentation\n<script>literal source</script>\n', null],
    ['report.py', 'application/octet-stream', '# Report\ndef report():\n    return "ready"\n', 'def'],
    ['main.rs', 'text/plain', 'fn main() {\n    let ready = true;\n}\n', 'fn'],
  ]) {
    test(`${surface} ${name} opens as readonly source with copy and original download`, async ({ page }, testInfo) => {
      const { open, dialog } = await setup(page, surface, { name, mime, respond: route => route.fulfill({ contentType: mime, body: content }) })
      await open.click()
      const editor = dialog.getByRole('textbox', { name, exact: true })
      await expect(editor).toHaveValue(content)
      await expect(editor).toHaveAttribute('readonly', '')
      await editor.focus()
      await editor.press('Control+End')
      await editor.press('Enter')
      await editor.press('Tab')
      await expect(editor).toHaveValue(content)
      if (token) {
        await expect(dialog.locator('.code-highlight span').filter({ hasText: new RegExp(`^${token}$`) })).toBeVisible()
      }
      await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
      await dialog.getByRole('button', { name: 'Copy', exact: true }).click()
      await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(content)
      const downloaded = page.waitForEvent('download')
      await dialog.getByRole('button', { name: /Download/ }).click()
      const download = await downloaded
      expect(download.suggestedFilename()).toBe(name)
      const chunks = []
      for await (const chunk of await download.createReadStream()) chunks.push(chunk)
      expect(Buffer.concat(chunks).toString('utf8')).toBe(content)
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await page.setViewportSize({ width: 390, height: 844 })
      await open.click()
      await expect(editor).toHaveValue(content)
      if (surface === 'document' && token === 'fn') await page.screenshot({ path: testInfo.outputPath('source-preview-mobile.png') })
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
    })
  }
}

for (const [surface, name, mime] of [
  ['document', 'NOTES.MD', 'text/markdown'],
  ['resource', 'NOTES.MD', 'text/markdown'],
  ['document', 'notes.txt', 'text/plain'],
  ['resource', 'notes.txt', 'text/plain'],
  ['message', 'notes.txt', 'text/plain'],
]) {
  test(`${surface} ${name} preview recovers after a failed read and discards a late context response`, async ({ page }) => {
    let reads = 0
    let release
    let waiting = false
    const { open, dialog } = await setup(page, surface, { name, mime, respond: async route => {
      reads++
      if (reads === 1) return route.fulfill({ status: 503 })
      if (reads === 2) {
        waiting = true
        await new Promise(resolve => { release = resolve })
        return route.fulfill({ contentType: 'text/markdown', body: '# Obsolete content' }).catch(() => {})
      }
      return route.fulfill({ contentType: 'text/markdown', body: markdown })
    } })
    await open.click()
    if (surface === 'document') {
      await expect(dialog).toHaveCount(0)
      await open.click()
    } else {
      await dialog.getByRole('button', { name: /Retry|Reload preview/ }).click()
    }
    await expect.poll(() => waiting).toBe(true)
    await page.evaluate(surface => window.testApp.setProps(surface === 'document' ? { documentId: 'document-2' } : { roomId: 'room-2' }), surface)
    await expect(dialog).toHaveCount(0)
    await open.click()
    const content = name.endsWith('.MD') ? dialog.getByRole('heading', { name: 'Project notes' }) : dialog.getByRole('textbox', { name, exact: true })
    await expect(content).toBeVisible()
    if (name.endsWith('.txt')) await expect(content).toHaveValue(markdown)
    release()
    await expect(dialog.getByRole('heading', { name: 'Obsolete content' })).toHaveCount(0)
    await expect(content).toBeVisible()
    if (name.endsWith('.txt')) await expect(content).toHaveValue(markdown)
  })
}
