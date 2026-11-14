import { test, expect } from '@playwright/test'
import { createDocument } from '../documents.mjs'
import { collectPageErrors } from '../page-errors.mjs'
import { notificationPrompt } from '../notification-prompt.mjs'

test('topic/tag moves persist while preserving the editor, other tags and manual placement', async ({ page, request }, testInfo) => {
  test.setTimeout(120_000)
  const errors = collectPageErrors(page)
  await page.addLocatorHandler(notificationPrompt(page), prompt => prompt.getByRole('button', { name: /^(Plus tard|Later)$/, exact: true }).click())
  const fixture = await (await request.post('/api/__test/seed')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const checked = async response => { expect(response.ok(), await response.text()).toBeTruthy(); return response.json() }
  const topics = []
  for (const name of ['Alpha', 'Beta']) topics.push(await checked(await request.post('/api/topics', { headers,
    data: { title: `Synthetic library ${name} ${fixture.agent_id}` } })))
  const items = []
  for (const [name, keywords] of [['Plan', ['source', 'retained', 'shared']], ['Figures', ['target', 'shared']], ['Inbox', ['retained']], ['Plain', []]]) {
    items.push(await checked(await createDocument(request, { headers, data: { owner_agent_id: fixture.agent_id,
      title: `Synthetic ${name} ${fixture.agent_id}`, keywords, payload: { text: `<p>Synthetic ${name} content</p>` } } })))
  }
  const account = await checked(await request.get('/api/auth/me', { headers }))
  expect(account.document_library_mode).toBe('folders')
  const personal = await checked(await request.post('/api/documents', { headers, data: {
    title: `Synthetic personal document ${fixture.agent_id}`, owner_kind: 'user', owner_id: account.id,
    actor_agent_id: null, document_type: 'text',
  } }))
  for (const [index, topic] of topics.entries()) await checked(await request.put(`/api/topics/resources/document/${items[index].id}`, {
    headers, data: { topic_id: topic.id, expected_topic_id: null, expected_lock_version: items[index].lock_version },
  }))
  const folder = await checked(await request.post('/api/documents/tags', { headers,
    data: { name: `Synthetic manual ${fixture.agent_id}`, parent_id: null } }))
  expect((await request.put(`/api/documents/${items[0].id}/tags`, { headers, data: { tag_id: folder.id } })).ok()).toBeTruthy()
  await errors.settle()
  await page.goto('/documents')
  await page.getByRole('tab', { name: /^(Sujets|Topics)$/, exact: true }).click()
  const tree = page.getByRole('tree', { name: /^(Sujets|Topics)$/, exact: true })
  await tree.getByText(topics[0].title, { exact: true }).click()
  await tree.getByText(topics[1].title, { exact: true }).click()
  await expect(tree.getByText('shared', { exact: true })).toHaveCount(2)
  await tree.getByText('source', { exact: true }).click()
  await tree.getByText('target', { exact: true }).click()
  const plan = tree.getByText(items[0].title, { exact: true })
  await plan.click()
  await expect(page.getByRole('textbox', { name: /^(Titre|Title)$/, exact: true })).toHaveValue(items[0].title)
  await errors.settle()
  const saved = page.waitForResponse(response => response.url().endsWith(`/topics/documents/${items[0].id}/classification`) && response.request().method() === 'PUT')
  await plan.dragTo(tree.getByText('target', { exact: true }))
  const response = await saved
  expect(response.status(), await response.text()).toBe(204)
  await errors.settle()
  const current = (await checked(await request.get(`/api/documents/${items[0].id}`, { headers }))).item
  expect(current.topic_id).toBe(topics[1].id)
  expect(current.keywords).toEqual(['retained', 'shared', 'target'])
  expect(current.revision).toBe(items[0].revision)
  expect(current.payload.text).toContain('Synthetic Plan content')
  const manual = await checked(await request.post('/api/documents/library', { headers, data: { tag_id: folder.id } }))
  expect(manual.entries.map(entry => entry.item.id)).toContain(items[0].id)
  await expect(page.getByRole('textbox', { name: /^(Titre|Title)$/, exact: true })).toHaveValue(items[0].title)
  await expect(plan).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('topics-in-application.png'), animations: 'disabled' })
  // Keep rendered shell diagnostics: isolated component mounts omit its tab overrides.
  const tabLayout = []
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    const tabs = page.locator('.document-library-tabs')
    await tabs.scrollIntoViewIfNeeded()
    tabLayout.push({ width, tabs: await tabs.getByRole('tab').evaluateAll(elements => elements.map(element => {
      const style = getComputedStyle(element)
      const label = element.querySelector('.q-tab__label')
      return { text: element.textContent, height: element.getBoundingClientRect().height,
        minHeight: style.minHeight, padding: style.padding, labelHeight: label.getBoundingClientRect().height }
    })) })
    await tabs.screenshot({ path: testInfo.outputPath(`document-tabs-${width}.png`), animations: 'disabled' })
  }
  await testInfo.attach('document-tab-layout', { body: JSON.stringify(tabLayout, null, 2), contentType: 'application/json' })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await errors.settle()
  await page.reload()
  await expect(page.getByRole('tab', { name: /^(Sujets|Topics)$/, exact: true })).toHaveAttribute('aria-selected', 'true')
  await tree.getByText(topics[1].title, { exact: true }).click()
  await tree.getByText('target', { exact: true }).click()
  await expect(plan).toBeVisible()
  const retainedPlan = await plan.elementHandle()
  await tree.getByText('retained', { exact: true }).click()
  await tree.getByText('shared', { exact: true }).click({ modifiers: ['Control'] })
  await tree.getByText('retained', { exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: /^(Fusionner les étiquettes|Merge tags)$/, exact: true }).click()
  const mergeDialog = page.getByRole('dialog')
  await mergeDialog.getByRole('combobox', { name: 'Destination', exact: true }).click()
  await page.getByRole('option', { name: 'shared', exact: true }).click()
  const merged = page.waitForResponse(response => response.url().endsWith('/documents/library/keywords') && response.request().method() === 'POST')
  await mergeDialog.getByRole('button', { name: /^(Confirmer|Confirm)$/, exact: true }).click()
  expect((await merged).status()).toBe(204)
  await expect(tree.getByText('retained', { exact: true })).toHaveCount(0)
  expect(await retainedPlan.evaluate(element => element.isConnected)).toBe(true)
  expect((await checked(await request.get(`/api/documents/${items[0].id}`, { headers }))).item.keywords).toEqual(['target', 'shared'])
  const list = page.getByRole('list', { name: /^(Documents non classés|Unclassified documents)$/, exact: true })
  await expect(list.getByText(items[2].title, { exact: true })).toBeVisible()
  await expect(list.getByText(items[0].title, { exact: true })).toHaveCount(0)
  await page.getByRole('tab', { name: /^(Agents|智能体)$/, exact: true }).click()
  const agentTree = page.getByRole('tree', { name: /^(Agents|智能体)$/, exact: true })
  const agentBranches = await checked(await request.get('/api/documents/library/agents', { headers }))
  const branch = agentBranches.find(branch => branch.id === fixture.agent_id)
  expect(branch.keywords).toEqual(['shared', 'target'])
  await agentTree.getByText(branch.title, { exact: true }).click()
  await agentTree.getByText(/^(Sans étiquette|Without a tag)$/, { exact: true }).click()
  await expect(agentTree.getByText(items[3].title, { exact: true })).toBeVisible()
  await expect(list.getByText(personal.title, { exact: true })).toBeVisible()
  await expect(list.getByText(items[2].title, { exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('agents-in-application.png'), animations: 'disabled' })
  await agentTree.getByText(/^(Tous les documents|All documents)$/, { exact: true }).click()
  const transferred = page.waitForResponse(response => response.url().endsWith(`/documents/${items[0].id}/owner`) && response.request().method() === 'PATCH')
  await agentTree.getByText(items[0].title, { exact: true }).dragTo(list)
  expect((await transferred).status()).toBe(200)
  await expect(list.getByText(items[0].title, { exact: true })).toBeVisible()
  const owned = (await checked(await request.get(`/api/documents/${items[0].id}`, { headers }))).item
  expect(owned.owner_agent_id).toBeNull(); expect(owned.owner_user_id).toBe(account.id)
  expect(owned.keywords).toEqual(['target', 'shared'])
  expect(owned.access.can_write).toBe(true)
  await errors.settle()
  expect((await checked(await request.get('/api/auth/me', { headers }))).document_library_mode).toBe('agents')
  await page.reload()
  await expect(page.getByRole('tab', { name: /^(Agents|智能体)$/, exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(agentTree.getByText(branch.title, { exact: true })).toBeVisible()
  // Submit the entire selection before leaving Documents; the server owns the move.
  await expect(list.getByText(personal.title, { exact: true })).toBeVisible()
  await expect(list.getByText(items[0].title, { exact: true })).toBeVisible()
  await list.getByText(personal.title, { exact: true }).click()
  await list.getByText(items[0].title, { exact: true }).click({ modifiers: ['Control'] })
  await expect(list.locator('.document-row[aria-selected="true"]')).toHaveCount(2)
  const batchRequest = page.waitForRequest(request => request.url().endsWith('/documents/library/owners') && request.method() === 'POST')
  const batchResponse = page.waitForResponse(response => response.url().endsWith('/documents/library/owners') && response.request().method() === 'POST')
  const destination = agentTree.getByText(branch.title, { exact: true })
  // Assert the submitted selection and persisted owners rather than a transient hover class.
  await list.getByText(personal.title, { exact: true }).dragTo(destination)
  const command = (await batchRequest).postDataJSON()
  expect(command.documents.map(entry => entry.document_id).sort()).toEqual([personal.id, items[0].id].sort())
  await page.locator('a[href="/"]').first().click()
  expect((await batchResponse).status()).toBe(204)
  for (const identity of [personal.id, items[0].id]) {
    const document = await checked(await request.get(`/api/documents/${identity}`, { headers }))
    expect(document.item.owner_agent_id).toBe(fixture.agent_id)
    expect(document.item.access.can_write).toBe(true)
  }
  await errors.settle()
  expect(errors()).toEqual([])
})
