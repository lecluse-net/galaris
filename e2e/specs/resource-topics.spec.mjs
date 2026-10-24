import { createDocument } from '../documents.mjs'
import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('Document and Dataset topic badges persist manual assignments through the real application', async ({ page, request }) => {
  const errors = collectPageErrors(page)
  test.setTimeout(120_000)
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt => prompt.getByRole('button', { name: /^(Plus tard|Later)$/, exact: true }).click())
  const fixture = await (await request.post('/api/__test/seed')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authentication).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const checked = async response => { expect(response.ok(), await response.text()).toBeTruthy(); return response.json() }
  const topics = []
  for (const label of ['Gardening', 'Plants']) topics.push(await checked(await request.post('/api/topics', {
    headers, data: { title: `Synthetic ${label} ${fixture.agent_id}` },
  })))
  const document = await checked(await createDocument(request, { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic topic document', node_kind: 'document',
    media_type: 'text/html', payload: { text: '<p>Synthetic topic content</p>' },
  } }))
  const dataset = await checked(await request.post('/api/datasets', { headers, data: {
    title: 'Synthetic topic Dataset', content: '{"quantity":3}',
  } }))
  for (const [kind, resource] of [['document', document], ['dataset', dataset]]) {
    await checked(await request.put(`/api/topics/resources/${kind}/${resource.id}`, { headers, data: {
      topic_id: topics[0].id, expected_topic_id: null, expected_lock_version: resource.lock_version,
    } }))
    await page.goto(kind === 'document' ? `/documents?document_id=${resource.id}` : `/dataset/${resource.id}`)
    await page.getByRole('button', { name: new RegExp(topics[0].title) }).click()
    const audit = page.getByRole('dialog').last()
    await audit.getByRole('combobox').click()
    await page.getByRole('option', { name: topics[1].title, exact: true }).click()
    const saved = page.waitForResponse(response => response.url().endsWith(`/topics/resources/${kind}/${resource.id}`) && response.request().method() === 'PUT')
    await audit.getByRole('button', { name: /^(Enregistrer le sujet|Save dossier)$/, exact: true }).click()
    expect((await saved).ok()).toBeTruthy()
    await expect(page.getByRole('button', { name: new RegExp(topics[1].title) })).toBeVisible()
    const read = await checked(await request.get(kind === 'document' ? `/api/documents/${resource.id}` : `/api/datasets/${resource.id}`, { headers }))
    const current = kind === 'document' ? read.item : read
    expect(current.topic_id).toBe(topics[1].id)
    expect(current.revision).toBe(resource.revision)
    if (kind === 'document') expect(current.payload.text).toContain('Synthetic topic content')
    else expect(current.content).toBe(dataset.content)
    await page.reload()
    await expect(page.getByRole('button', { name: new RegExp(topics[1].title) })).toBeVisible()
  }
  const related = await checked(await request.get(`/api/topics/${topics[1].id}/content`, { headers }))
  expect(related.documents.map(item => item.id)).toContain(document.id)
  expect(related.datasets.map(item => item.id)).toContain(dataset.id)

  const usage = await checked(await request.post(`/api/__test/topics/${topics[1].id}/usage`, {
    params: { agent_id: fixture.agent_id, room_id: fixture.rooms[0] },
  }))
  const loaded = page.waitForResponse(response => new URL(response.url()).pathname === '/api/topics')
  await page.goto('/topic')
  expect((await loaded).ok()).toBeTruthy()
  const month = page.getByRole('combobox', { name: /^(Mois|Month)$/ })
  const row = page.getByRole('row').filter({ has: page.getByRole('link', { name: topics[1].title, exact: true }) })
  const chooseMonth = async (label, value, expected) => {
    await month.click()
    const response = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname === '/api/topics' && url.searchParams.get('month') === value
    })
    await page.getByRole('option', { name: label }).click()
    const result = await response
    expect(result.ok(), await result.text()).toBeTruthy()
    const summary = (await result.json()).items.find(item => item.id === topics[1].id)
    expect(summary.llm_calls).toBe(expected.llm_calls)
    expect(summary.inference_cost).toBe(expected.inference_cost)
    await row.locator('.topic-cost').hover()
    await expect(page.getByRole('tooltip')).toContainText(String(expected.llm_calls))
    await month.focus()
  }
  await chooseMonth(/juillet 2026|July 2026/i, '2026-07', usage.july)
  await chooseMonth(/août 2026|August 2026/i, '2026-08', usage.august)
  await page.reload()
  await chooseMonth(/juillet 2026|July 2026/i, '2026-07', usage.july)
  expect(errors()).toEqual([])
})
