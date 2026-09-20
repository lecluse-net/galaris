import { test, expect, mount, jsonRoute } from './fixtures.mjs'

// The same real geometry and camera checks previously lived in an uncollected manual script.
test.use({ launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } })
const cube = 'v -1 -1 -1\nv 1 -1 -1\nv 1 1 -1\nv -1 1 -1\nv -1 -1 1\nv 1 -1 1\nv 1 1 1\nv -1 1 1\nf 1 4 3 2\nf 5 6 7 8\nf 1 2 6 5\nf 4 8 7 3\nf 1 5 8 4\nf 2 3 7 6\n'
const file = { id: 'model-1', uri: 'chat://room/model-1', name: 'cube.obj', mime_type: 'model/obj', media_type: 'model/obj', kind: 'file', size_bytes: cube.length }

for (const surface of ['document', 'message', 'resource']) {
  test(`${surface} 3D preview renders geometry, supports camera navigation and cleans up`, async ({ page }) => {
    await page.route('**/api/memory/documents/document-1/attachments/model-1?*', route => route.fulfill({ contentType: 'model/obj', body: cube }))
    await page.route('**/api/chat/rooms/room-1/files/model-1*', route => route.fulfill({ contentType: 'model/obj', body: cube }))
    await page.route('**/api/chat/rooms/room-1/messages/message-1/previews/content?*', route => route.fulfill({ contentType: 'model/obj', body: cube }))
    await jsonRoute(page, /\/previews(?:\?.*)?$/, [{ uri: file.uri, kind: 'file', title: file.name, subtitle: '', description: '', media_type: file.mime_type, content: null, content_format: 'text', truncated: false, image_available: false, download_available: true, open_mode: 'inline', external_url: null, embed_url: null, metadata: {} }])
    await jsonRoute(page, '**/api/chat/rooms/room-1/speech/status*', { available_agent_ids: [] })
    const component = surface === 'document' ? 'app/memory/components/DocumentAttachments.vue' : `app/chat/components/${surface === 'message' ? 'MessageTimeline' : 'MessageResourcePreviews'}.vue`
    const props = surface === 'document'
      ? { documentId: 'document-1', agentId: 1, attachments: [file] }
      : surface === 'resource' ? { roomId: 'room-1', messageId: 'message-1' }
      : { roomId: 'room-1', agentId: 1, agentName: 'Test', activity: [], liveRound: null, messages: [{ id: 'message-1', external_id: 'external-1', text: '', files: [file], is_mine: true, sender: { display_name: 'Test', is_ai: false }, created_at: '2026-01-01T12:00:00Z' }] }
    await mount(page, component, { props })
    const image = page.locator('.model3d-thumbnail img').first()
    await expect(image).toBeVisible()
    const rendering = await image.evaluate(async element => {
      await element.decode()
      const canvas = document.createElement('canvas')
      canvas.width = element.naturalWidth; canvas.height = element.naturalHeight
      const ctx = canvas.getContext('2d'); ctx.drawImage(element, 0, 0)
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data
      const colors = new Set()
      for (let i = 0; i < pixels.length; i += 4) colors.add(`${pixels[i]},${pixels[i + 1]},${pixels[i + 2]}`)
      return { width: canvas.width, colors: colors.size }
    })
    expect(rendering.width).toBeGreaterThanOrEqual(320)
    expect(rendering.colors).toBeGreaterThan(4)
    await page.locator(surface === 'document' ? '.document-attachments .resource-preview-main' : surface === 'message' ? '.model3d-attachment' : '.resource-preview-main').click()
    const canvas = page.locator('.model3d-viewer canvas')
    await expect(canvas).toBeFocused()
    const changesRendering = async (action, label = 'camera interaction') => {
      const before = await canvas.screenshot()
      await action()
      await expect.poll(async () => (await canvas.screenshot()).equals(before), { message: label }).toBe(false)
    }
    await changesRendering(() => page.getByRole('button', { name: 'Zoom in', exact: true }).click())
    await canvas.focus()
    for (const key of ['ArrowLeft', 'Shift+ArrowRight', '+', 'Home']) await changesRendering(() => canvas.press(key), key)
    if (surface === 'document') {
      await page.getByRole('button', { name: 'Enter fullscreen', exact: true }).click()
      await expect.poll(() => page.evaluate(() => document.fullscreenElement !== null)).toBe(true)
      await page.getByRole('button', { name: 'Exit fullscreen', exact: true }).press('Enter')
      await expect.poll(() => page.evaluate(() => document.fullscreenElement !== null)).toBe(false)
      const bounds = await canvas.boundingBox()
      const x = bounds.x + bounds.width / 2, y = bounds.y + bounds.height / 2
      const drag = async button => {
        await page.mouse.move(x, y)
        await page.mouse.down({ button })
        await page.mouse.move(x + 90, y + 40, { steps: 8 })
        await page.mouse.up({ button })
      }
      for (const button of ['left', 'right', 'middle']) await changesRendering(() => drag(button))
      await changesRendering(() => page.mouse.wheel(0, -220))
      await page.getByRole('button', { name: '3D navigation controls', exact: true }).click()
      await expect(page.getByText('Keyboard: Shift + arrow keys to pan the view.', { exact: true })).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.locator('.model3d-viewer')).toHaveCount(1)
      await canvas.focus()
    }
    await page.keyboard.press('Escape')
    await expect(page.locator('.model3d-viewer')).toHaveCount(0)
    if (surface === 'resource') {
      await page.setViewportSize({ width: 390, height: 844 })
      await page.locator('.resource-preview-main').click()
      await expect(canvas).toBeVisible()
      const bounds = await page.locator('.model3d-viewer').boundingBox()
      expect(bounds.width).toBeLessThanOrEqual(390)
      expect(bounds.height).toBeLessThan(844)
      await page.mouse.click(2, 700)
      await expect(page.locator('.model3d-viewer')).toHaveCount(0)
    }
    await page.evaluate(() => window.testApp.unmount())
    await expect(page.locator('canvas')).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('')
  })
}
