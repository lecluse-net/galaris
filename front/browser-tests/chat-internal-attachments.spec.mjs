import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const uri = 'file://00000000-0000-4000-8000-000000000001'
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64')

for (const width of [1440, 390]) test(`conversation internal files stay outside text and survive send failure at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  await jsonRoute(page, '**/api/chat/emojis/frequent', { items: [] })
  await jsonRoute(page, '**/api/file-share/browser/schemes?*', [{ scheme: 'file', label: 'Managed files', capabilities: ['list'], native: true }])
  await jsonRoute(page, '**/api/file-share/browser/entries?*', {
    entries: [{ uri, name: 'Synthetic image.png', is_collection: false, media_type: 'image/png', size: png.length, capabilities: ['read', 'info'] }], next_cursor: null, truncated: false,
  })
  await page.route('**/api/file-share/browser/thumbnail?*', route => route.fulfill({ status: 404 }))
  await mount(page, 'app/chat/components/Composer.vue', { props: { roomId: 'room-a', agentId: 7, sending: false } })
  const input = page.locator('textarea')
  if (width < 1024) {
    await page.getByRole('button', { name: 'Add attachments', exact: true }).click()
    await page.getByText('Add an internal attachment', { exact: true }).click()
  } else {
    await page.getByRole('button', { name: 'Add an internal attachment', exact: true }).click()
  }
  if (width < 1024) await page.getByRole('button', { name: 'Show locations', exact: true }).click()
  await page.locator('.file-scheme-label').filter({ hasText: /^Managed files$/ }).click()
  await page.getByRole('button', { name: 'Select Synthetic image.png', exact: true }).click()
  await page.getByRole('button', { name: 'Select', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(input).toHaveValue('')
  const removeInternal = page.getByRole('button', { name: 'Remove Synthetic image.png', exact: true })
  await expect(removeInternal).toBeVisible()
  await page.locator('input[type=file]').setInputFiles({ name: 'Local notes.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic local notes') })
  await page.screenshot({ path: testInfo.outputPath('composer-internal-file.png') })
  const post = page.getByRole('button', { name: 'Post', exact: true })
  await post.click()
  const sent = () => page.evaluate(() => {
    const event = window.testApp.events.filter(event => event.name === 'send').at(-1)
    return event && [event.args[0], event.args[1]?.map(file => file.name), event.args[5]]
  })
  await expect.poll(sent).toEqual(['', ['Local notes.txt'], [uri]])
  await page.evaluate(() => window.testApp.events.filter(event => event.name === 'send').at(-1).args[4](false))
  await expect(post).toBeEnabled()
  await expect(removeInternal).toBeVisible()
  await input.fill('Image for review')
  await post.click()
  await expect.poll(sent).toEqual(['Image for review', ['Local notes.txt'], [uri]])
  await page.evaluate(() => window.testApp.events.filter(event => event.name === 'send').at(-1).args[4](true))
  await expect(input).toHaveValue('')
  await expect(removeInternal).toHaveCount(0)
  await expect(post).toBeDisabled()

  await jsonRoute(page, '**/api/chat/rooms/room-a/speech/status*', { available_agent_ids: [] })
  await jsonRoute(page, '**/api/chat/rooms/room-a/messages/message-a/previews', [{
    uri, kind: 'file', title: 'Synthetic image.png', subtitle: '', description: '', media_type: 'image/png',
    content: null, content_format: 'none', truncated: false, image_available: false, download_available: true,
    open_mode: 'inline', external_url: null, embed_url: null, metadata: {}, deleted: false,
  }])
  await page.route('**/api/chat/rooms/room-a/messages/message-a/previews/content?*', route => {
    expect(new URL(route.request().url()).searchParams.get('uri')).toBe(uri)
    return route.fulfill({ contentType: 'image/png', body: png })
  })
  await mount(page, 'app/chat/components/MessageTimeline.vue', { props: {
    roomId: 'room-a', agentId: 7, agentName: 'Synthetic agent', activity: [], liveRound: null,
    messages: [{ id: 'message-a', external_id: 'message-a', room_id: 'room-a', direction: 'inbound', text: '',
      resource_uris: [uri], files: [], sender: null, status: 'received', is_mine: true, created_at: '2026-10-01T12:00:00Z' }],
  } })
  const image = page.getByRole('img', { name: 'Synthetic image.png', exact: true })
  await expect(image).toBeVisible()
  await expect(image).toHaveJSProperty('naturalWidth', 1)
  await page.screenshot({ path: testInfo.outputPath('message-internal-file.png') })
})
