import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

// Playwright's worker blocker reads navigator.serviceWorker in opaque frames.
// Keep the document sandbox intact and avoid injecting that failing script.
test.use({ serviceWorkers: 'allow' })

test('Documents and Datasets use separate libraries and creation paths', async ({ page, request }) => {
  const pageErrors = collectPageErrors(page)
  test.setTimeout(120_000)
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt => prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  // A sidebar backdrop behind an open dialog must not interrupt dialog actions.
  await page.addLocatorHandler(page.locator('body:not(:has([role="dialog"])) .q-drawer__backdrop'),
    backdrop => backdrop.click({ position: { x: 380, y: 150 } }))
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
  const rejected = await request.post('/api/documents', { headers, data: {
    owner_kind: 'agent', owner_id: fixture.agent_id, actor_agent_id: fixture.agent_id,
    document_type: 'dataset', title: 'Synthetic rejected Dataset',
  } })
  expect(rejected.status()).toBe(422)

  await page.goto('/documents')
  await page.getByRole('button', { name: /^(Créer un document|Create document)$/, exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('combobox', { name: /^(Type de document|Document type)$/, exact: true })).toHaveCount(0)
  await dialog.getByRole('textbox', { name: /^(Titre|Title)$/, exact: true }).fill('Synthetic separate document')
  const created = page.waitForResponse(response => response.url().endsWith('/documents') && response.request().method() === 'POST')
  await dialog.getByRole('button', { name: /^(Créer|Create)$/, exact: true }).click()
  const document = await checked(await created)
  expect(document.document_type).toBe('html')
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: /^(Titre|Title)$/, exact: true })).toHaveValue(document.title)
  await expect(page.locator('[data-editor-surface]')).toBeVisible()
  const library = await checked(await request.post('/api/documents/library', { headers, data: {} }))
  expect(library.entries.map(entry => entry.item.id)).toContain(document.id)
  expect(library.entries.map(entry => entry.item.id)).not.toContain(dataset.id)
  expect(library.entries.every(entry => entry.item.document_type !== 'dataset')).toBe(true)
  const editor = page.locator('[data-editor-surface]')
  await editor.click()
  await page.getByRole('button', { name: /^(Lien Galaris|Galaris link)$/, exact: true }).first().click()
  await page.getByRole('dialog').getByText('Galaris Datasets', { exact: true }).click()
  await page.getByRole('dialog').locator('.file-main').getByRole('button', { name: new RegExp(`^(Select|Sélectionner) ${dataset.title}$`) }).click()
  const saved = page.waitForResponse(response => response.url().includes(`/documents/${document.id}`) && response.request().method() === 'PATCH')
  await page.getByRole('dialog').getByRole('button', { name: /^(Sélectionner|Select)$/, exact: true }).click()
  expect((await saved).ok()).toBeTruthy()
  await expect(editor.getByRole('link', { name: dataset.title, exact: true })).toHaveAttribute('data-rich-reference', `data://${dataset.id}`)
  await expect(page.locator('.document-editor-attachments .resource-preview-card')).toHaveCount(0)
  await page.reload()
  await expect(editor.getByRole('link', { name: dataset.title, exact: true })).toBeVisible()
  const usages = await checked(await request.get(`/api/datasets/${dataset.id}/usages?kind=documents`, { headers }))
  expect(usages.items.map(item => item.id)).toContain(`document:${document.id}`)
  await editor.getByRole('link', { name: dataset.title, exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: test.info().outputPath('documents-library.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await editor.getByRole('link', { name: dataset.title, exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: test.info().outputPath('document-dataset-mobile.png'), fullPage: true, animations: 'disabled' })

  // Historical redirects are covered by backend/component fixtures. Public creation
  // must never manufacture another historical Dataset Document.
  const rejectedMemory = await request.post('/api/memory/items', { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic rejected JSON document', node_kind: 'document',
    document_type: 'dataset', media_type: 'application/json', payload: { text: '{"legacy":true}' },
  } })
  expect(rejectedMemory.status()).toBe(422)

  await editor.getByRole('link', { name: dataset.title, exact: true }).click()
  await page.keyboard.press('Alt+Enter')
  await expect(page.getByRole('region', { name: /^(Dataset editor|Éditeur du jeu de données)$/ })
    .getByRole('textbox', { name: /^(Titre|Title)$/, exact: true })).toHaveValue(dataset.title)
  expect((await checked(await request.get(`/api/datasets/${dataset.id}`, { headers }))).content).toBe('{"amount":125000}')
  expect(pageErrors()).toEqual([])
})
