import { test, expect } from '@playwright/test'

test('Dataset documents keep their type, exact JSON and revisions through the real editor', async ({ page, request }) => {
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
  const created = await request.post('/api/memory/documents', { headers, data: {
    owner_kind: 'agent', owner_id: fixture.agent_id, actor_agent_id: fixture.agent_id,
    document_type: 'dataset', title: 'Credit scenarios E2E',
  } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const item = await created.json()
  expect(item.document_type).toBe('dataset')
  expect(item.media_type).toBe('application/json')
  const itemUrl = `/api/memory/items/${item.id}`
  await page.goto(`/memory/documents?document_id=${item.id}`)
  const editor = page.getByRole('textbox', { name: /^(Content|Contenu)$/, exact: true })
  await expect(editor).toHaveValue('{}')
  const source = '{\n  "amount": 125000,\n  "label": "<b>Literal</b>",\n  "scenarios": [12, 24]\n}\n'
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes(itemUrl))
  await editor.fill(source)
  expect((await saved).ok()).toBeTruthy()
  const persisted = await (await request.get(`${itemUrl}?agent_id=${fixture.agent_id}`, { headers })).json()
  expect(persisted.document_type).toBe('dataset')
  expect(persisted.payload.text).toBe(source)
  expect(persisted.revision).toBe(2)
  await page.reload()
  await expect(editor).toHaveValue(source)

  for (const data of [
    { document_type: 'html' },
    { media_type: 'text/html', payload: { text: '<p>Changed</p>' } },
    { payload: { text: '{' } },
  ]) {
    const response = await request.put(`${itemUrl}?actor_agent_id=${fixture.agent_id}`, {
      headers, data: { expected_revision: 2, ...data },
    })
    expect([409, 422]).toContain(response.status())
  }
  const stable = await (await request.get(`${itemUrl}?agent_id=${fixture.agent_id}`, { headers })).json()
  expect(stable.payload.text).toBe(source)
  expect(stable.revision).toBe(2)
  const library = await request.post('/api/memory/documents/library', { headers, data: { document_type: 'dataset', sort_by: 'document_type' } })
  expect(library.ok(), await library.text()).toBeTruthy()
  expect((await library.json()).entries.map(entry => entry.item.id)).toContain(item.id)
  const restored = await request.post(`/api/memory/documents/${item.id}/content-revisions/1/restore`, { headers, data: { expected_revision: 2 } })
  expect(restored.ok(), await restored.text()).toBeTruthy()
  expect((await restored.json()).document_type).toBe('dataset')
  await page.reload()
  await expect(editor).toHaveValue('{}')
})
