import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('Documents and Datasets use separate libraries and creation paths', async ({ page, request }) => {
  const pageErrors = collectPageErrors(page)
  test.setTimeout(120_000)
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt => prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop => backdrop.click({ position: { x: 380, y: 150 } }))
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
  const dataset = await checked(await request.post('/api/datasets', { headers, data: {
    title: 'Synthetic separate Dataset', content: '{"amount":125000}',
  } }))
  const rejected = await request.post('/api/memory/documents', { headers, data: {
    owner_kind: 'agent', owner_id: fixture.agent_id, actor_agent_id: fixture.agent_id,
    document_type: 'dataset', title: 'Synthetic rejected Dataset',
  } })
  expect(rejected.status()).toBe(422)

  await page.goto('/documents')
  await page.getByRole('button', { name: /^(Créer un document|Create document)$/, exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('combobox', { name: /^(Type de document|Document type)$/, exact: true })).toHaveCount(0)
  await dialog.getByRole('textbox', { name: /^(Titre|Title)$/, exact: true }).fill('Synthetic separate document')
  const created = page.waitForResponse(response => response.url().endsWith('/memory/documents') && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: /^(Créer|Create)$/, exact: true }).click()
  const document = await checked(await created)
  expect(document.document_type).toBe('html')
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: /^(Titre|Title)$/, exact: true })).toHaveValue(document.title)
  await expect(page.locator('.ck-editor__editable')).toBeVisible()
  const library = await checked(await request.post('/api/memory/documents/library', { headers, data: {} }))
  expect(library.entries.map(entry => entry.item.id)).toContain(document.id)
  expect(library.entries.map(entry => entry.item.id)).not.toContain(dataset.id)
  expect(library.entries.every(entry => entry.item.document_type !== 'dataset')).toBe(true)
  await page.getByRole('button', { name: /^(Joindre un jeu de données|Attach a Dataset)$/ }).click()
  await page.getByRole('dialog').getByRole('combobox', { name: /^(Jeu de données|Dataset)$/ }).click()
  await page.getByRole('option', { name: dataset.title, exact: true }).click()
  const attached = page.waitForResponse(response => response.url().includes('/dataset-attachments') && response.request().method() === 'PUT')
  await page.getByRole('dialog').getByRole('button', { name: /^(Joindre|Attach)$/, exact: true }).click()
  expect((await attached).ok()).toBeTruthy()
  await expect(page.getByRole('link', { name: dataset.title, exact: true })).toHaveAttribute('href', `/dataset/${dataset.id}`)
  await page.reload()
  await expect(page.getByRole('link', { name: dataset.title, exact: true })).toBeVisible()
  const usages = await checked(await request.get(`/api/datasets/${dataset.id}/usages?kind=documents`, { headers }))
  expect(usages.items.map(item => item.id)).toContain(`document:${document.id}`)
  await page.getByRole('link', { name: dataset.title, exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: test.info().outputPath('documents-library.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await page.getByRole('link', { name: dataset.title, exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: test.info().outputPath('document-dataset-mobile.png'), fullPage: true, animations: 'disabled' })

  // Public creation must not manufacture historical Dataset Documents.
  const rejectedMemory = await request.post('/api/memory/items', { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic rejected JSON document', node_kind: 'document',
    document_type: 'dataset', media_type: 'application/json', payload: { text: '{"legacy":true}' },
  } })
  expect(rejectedMemory.status()).toBe(422)

  await page.goto(`/dataset/${dataset.id}`)
  await expect(page.getByRole('textbox', { name: /^(Titre|Title)$/, exact: true })).toHaveValue(dataset.title)
  expect((await checked(await request.get(`/api/datasets/${dataset.id}`, { headers }))).content).toBe('{"amount":125000}')
  expect(pageErrors()).toEqual([])
})
