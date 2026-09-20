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
  for (const memoryType of ['core', 'working', 'episodic', 'semantic', 'procedural', 'social']) {
    const response = await request.post('/api/memory/items', { headers, data: { owner_agent_id: fixture.agent_id, title: `HTML ${memoryType}`, memory_type: memoryType, media_type: 'text/html', payload: { text: corpus + `<p>${memoryType}</p>` } } })
    expect(response.ok(), await response.text()).toBeTruthy()
    const item = await response.json()
    expect(item.media_type).toBe('text/html')
    expect(item.content_profile).toBe('rich-text')
    expect(item.memory_type).toBe(memoryType)
  }
  // Editorial bodies are static HTML. Executable HTML belongs to attachments;
  // an older test expected scripts to survive inline in the editor.
  const documentData = { owner_agent_id: fixture.agent_id, title: 'Document HTML E2E', node_kind: 'document', memory_type: 'working', media_type: 'text/html' }
  const rejected = await request.post('/api/memory/items', { headers, data: {
    ...documentData, payload: { text: corpus + '<script>window.editorialE2E=true</script>' },
  } })
  expect(rejected.status()).toBe(422)
  const callout = '<blockquote class="galaris-callout galaris-callout-info"><p>Document éditorial</p></blockquote>'
  const created = await request.post('/api/memory/items', { headers, data: { ...documentData, payload: { text: corpus + callout } } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const item = await created.json()
  const oldClient = await request.put(`/api/memory/items/${item.id}?actor_agent_id=${fixture.agent_id}`, { headers: { Authorization: headers.Authorization }, data: { expected_revision: item.revision, payload: { text: 'Old client' } } })
  expect(oldClient.status()).toBe(409)
  const forbidden = await request.put(`/api/agents/${fixture.agent_id}`, { headers, data: { personality: '<img src="https://example.invalid/image.png">' } })
  expect(forbidden.status()).toBe(422)
  await page.goto(`/memory/documents?document_id=${item.id}`)
  const editor = page.locator('.document-editor .ck-editor__editable')
  await expect(editor.locator('u')).toHaveText('Texte souligné')
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  await editor.locator('h2').click()
  await page.keyboard.press('End')
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes(`/memory/items/${item.id}`))
  await page.keyboard.type('!')
  expect((await saved).ok()).toBeTruthy()
  const persisted = await (await request.get(`/api/memory/items/${item.id}?agent_id=${fixture.agent_id}`, { headers })).json()
  expect(persisted.media_type).toBe('text/html')
  expect(persisted.payload.text).toContain('<u>Texte souligné</u>')
  expect(persisted.payload.text).toContain('colspan="2"')
  expect(persisted.payload.text).toContain('  &lt;p&gt;\n    a  b\n')
  expect(persisted.payload.text).not.toContain('<script')
  expect(persisted.payload.text).toContain('galaris-callout-info')
  await page.reload()
  await expect(editor.locator('h2')).toHaveText('Été!')
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  expect(await page.evaluate(() => window.editorialE2E)).toBeUndefined()
  // Source editing exposes the saved editorial HTML, including escaped code.
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(page.locator('.ck-source-editing-area textarea')).toHaveValue(/&lt;p&gt;/)
  expect(await page.evaluate(() => window.editorialE2E)).toBeUndefined()
})
