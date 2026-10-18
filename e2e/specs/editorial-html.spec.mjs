import { test, expect } from '@playwright/test'

test('editorial HTML survives real API storage, browser editing and reload', async ({ page, request }) => {
  const fixture = await (await request.post('/api/__test/seed')).json()
  const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
  await page.goto('/user/login')
  await refresh
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const corpus = '<h2>Été</h2><p><u>Texte souligné</u></p><table><tbody><tr><th colspan="2" colwidth="150,200"><p>En-tête</p></th></tr><tr><td><p>A</p></td><td><p>B</p></td></tr></tbody></table><pre><code>  &lt;p&gt;\n    a  b\n</code></pre>'
  {
    const response = await request.post('/api/memory/items', { headers, data: { owner_agent_id: fixture.agent_id, title: 'HTML memory', media_type: 'text/html', payload: { text: corpus } } })
    expect(response.ok(), await response.text()).toBeTruthy()
    const item = await response.json()
    expect(item.media_type).toBe('text/html')
    expect(item.content_profile).toBe('rich-text')
  }
  // Memory keeps the static rich-text contract. Executable document isolation
  // is exercised separately by document-apps.spec.mjs.
  const documentData = { owner_agent_id: fixture.agent_id, title: 'Document HTML E2E', node_kind: 'document', media_type: 'text/html' }
  const rejected = await request.post('/api/memory/items', { headers, data: {
    ...documentData, node_kind: 'memory', title: 'Rejected scripted memory',
    payload: { text: corpus + '<script>window.editorialE2E=true</script>' },
  } })
  expect(rejected.status()).toBe(422)
  const callout = '<blockquote class="galaris-callout galaris-callout-info"><p>Document éditorial</p></blockquote>'
  const created = await request.post('/api/memory/items', { headers, data: { ...documentData, payload: { text: corpus + callout } } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const item = await created.json()
  const oldClient = await request.patch(`/api/memory/documents/${item.id}?actor_agent_id=${fixture.agent_id}`, { headers: { Authorization: headers.Authorization }, data: { expected_revision: item.revision, payload: { text: 'Old client' } } })
  expect(oldClient.status()).toBe(409)
  const forbidden = await request.put(`/api/agents/${fixture.agent_id}`, { headers, data: { personality: '<img src="https://example.invalid/image.png">' } })
  expect(forbidden.status()).toBe(422)
  await page.goto(`/memory/documents?document_id=${item.id}`)
  const editor = page.locator('.document-editor [data-editor-surface]')
  await expect(editor.locator('u')).toHaveText('Texte souligné')
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  await editor.locator('h2').click()
  await page.keyboard.press('End')
  const saved = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/memory/documents/${item.id}`)
    && response.request().postDataJSON()?.payload?.text?.includes('<h3>Été!</h3>'))
  const modifier = await page.evaluate(() => /Macintosh|iPhone|iPad/.test(navigator.userAgent) ? 'Meta' : 'Control')
  await page.keyboard.press(`${modifier}+Alt+Digit3`)
  await expect(editor.locator('h3')).toHaveText('Été')
  await page.keyboard.type('!')
  expect((await saved).ok()).toBeTruthy()
  const persisted = (await (await request.get(`/api/memory/documents/${item.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  expect(persisted.media_type).toBe('text/html')
  expect(persisted.payload.text).toContain('<u>Texte souligné</u>')
  expect(persisted.payload.text).toContain('colspan="2"')
  expect(persisted.payload.text).toContain('  &lt;p&gt;\n    a  b\n')
  expect(persisted.payload.text).not.toContain('<script')
  expect(persisted.payload.text).toContain('galaris-callout-info')
  expect(persisted.payload.text).toContain('<h3>Été!</h3>')
  await page.reload()
  await expect(editor.locator('h3')).toHaveText('Été!')
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  expect(await page.evaluate(() => window.editorialE2E)).toBeUndefined()
  const upload = await request.post(`/api/memory/documents/${item.id}/attachments?actor_agent_id=${fixture.agent_id}`, {
    headers, multipart: { file: { name: 'synthetic-resize.png', mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGNkYPjPwMDAxMDAwMDAAAALHwEDmIWXfgAAAABJRU5ErkJggg==', 'base64') } },
  })
  expect(upload.ok(), await upload.text()).toBeTruthy()
  const attachment = await upload.json()
  const imageUri = `document://${item.id}/attachments/${attachment.id}`
  const latest = (await (await request.get(`/api/memory/documents/${item.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  const imageSaved = await request.patch(`/api/memory/documents/${item.id}?actor_agent_id=${fixture.agent_id}`, { headers, data: {
    expected_revision: latest.revision, payload: { text: latest.payload.text
      + `<figure class="image"><img width="200" alt="Synthetic resize image" src="${imageUri}"></figure><p>After image</p>` },
  } })
  expect(imageSaved.ok(), await imageSaved.text()).toBeTruthy()
  await page.reload()
  const picture = editor.getByAltText('Synthetic resize image')
  await expect(picture).toHaveJSProperty('naturalWidth', 2)
  await picture.click()
  const handle = await editor.locator('.galaris-image-resize').boundingBox()
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down()
  await page.mouse.move(handle.x + handle.width / 2 + 80, handle.y + handle.height / 2, { steps: 8 })
  const resizedWidth = (await picture.boundingBox()).width
  const resizedSave = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/memory/documents/${item.id}`)
    && response.request().postDataJSON()?.payload?.text?.includes('image_resized'))
  await page.mouse.up()
  expect((await resizedSave).ok()).toBeTruthy()
  const resizedDocument = (await (await request.get(`/api/memory/documents/${item.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  expect(resizedDocument.payload.text).toContain(imageUri)
  expect(resizedDocument.payload.text).toMatch(/width: [0-9.]+%/)
  expect(resizedDocument.payload.text).not.toMatch(/blob:|galaris-image-resize/)
  await page.reload()
  await expect(picture).toHaveJSProperty('naturalWidth', 2)
  await expect.poll(async () => (await picture.boundingBox()).width).toBeCloseTo(resizedWidth, 0)
  await expect(page.getByRole('button', { name: 'Source', exact: true })).toHaveCount(0)
  expect(resizedDocument.payload.text).toContain('&lt;p&gt;')
  expect(await page.evaluate(() => window.editorialE2E)).toBeUndefined()
})
