import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('native Processes and runs remain live references in authored Documents', async ({ page, request }) => {
  test.setTimeout(120_000)
  const errors = collectPageErrors(page)
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt => prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  const fixture = await (await request.post('/api/__test/seed?mode=process-human')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await login).json()
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  const checked = async response => { expect(response.ok(), await response.text()).toBeTruthy(); return response.json() }
  const definition = await checked(await request.post('/api/processes/internal/definitions', { headers, data: {
    agent_id: fixture.agent_id, owner: 'agent', title: 'Synthetic cited process',
    graph: { schema_version: 'galaris.bpmn/v2', inputs: [], outputs: [], actors: [],
      nodes: [{ id: 'start', kind: 'start', title: 'Synthetic start' }, { id: 'end', kind: 'end', title: 'Synthetic end' }],
      flows: [{ id: 'finish', source: 'start', target: 'end' }] },
  } }))
  const run = await checked(await request.post(`/api/processes/internal/definitions/${definition.code}/runs`, {
    headers, data: { agent_id: fixture.agent_id, input: {} },
  }))
  const processUri = `galaris://processes/${definition.code}`, runUri = `galaris://processes/runs/${run.id ?? run.run_id}`
  const html = `<p>Synthetic guide.</p><blockquote class="galaris-link-card galaris-process-diagram"><p><a href="${processUri}">Synthetic cited process</a></p></blockquote><p><a href="${runUri}">Synthetic cited execution</a></p>`
  const document = await checked(await request.post('/api/memory/items', { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic process citations', node_kind: 'document',
    media_type: 'text/html', payload: { text: html },
  } }))
  await page.goto(`/documents?document_id=${document.id}`)
  const inline = page.locator('.process-preview--inline')
  await expect(inline.getByRole('button', { name: 'Synthetic start · start', exact: true })).toBeVisible()
  await inline.hover()
  await inline.getByRole('button', { name: /^(Zoom in|Agrandir)$/, exact: true }).click()
  await inline.getByRole('button', { name: /^(Open preview|Ouvrir l’aperçu)$/, exact: true }).click()
  await expect(page.getByRole('dialog').getByText(/^(Read-only access|Accès en lecture seule)$/)).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('button', { name: /^(Save|Enregistrer)$/, exact: true })).toHaveCount(0)
  await page.getByRole('dialog').getByRole('button', { name: /^(Close|Fermer)$/, exact: true }).click()
  const editor = page.locator('[data-editor-surface]')
  await editor.click(); await page.keyboard.press('Control+End'); await page.keyboard.press('Enter')
  await page.getByRole('button', { name: /^(Galaris link|Lien Galaris)$/, exact: true }).click()
  await page.getByRole('dialog').locator('.file-scheme-label').filter({ hasText: /^Galaris business resources$/ }).click()
  const files = page.getByRole('dialog').locator('.file-main')
  await files.getByRole('button', { name: /^(Select|Sélectionner) Processes$/, exact: true }).dblclick()
  await files.getByRole('button', { name: new RegExp(`^(Select|Sélectionner) ${definition.title}$`), exact: true }).click()
  await files.getByRole('button', { name: /^(Select|Sélectionner) Runs$/, exact: true }).dblclick()
  await files.getByRole('button', { name: new RegExp(`^(Select|Sélectionner) ${definition.title} ·`), exact: false }).click()
  const saving = page.waitForResponse(response => response.url().includes(`/memory/documents/${document.id}`) && response.request().method() === 'PATCH')
  await page.getByRole('dialog').getByRole('button', { name: /^(Select|Sélectionner)$/, exact: true }).click()
  expect((await saving).ok()).toBeTruthy()
  await page.locator('.document-editor-attachments').scrollIntoViewIfNeeded()
  await expect(page.locator('.document-editor-attachments .resource-preview-card')).toHaveCount(0)
  await expect(page.locator('.document-editor-attachments').getByRole('button', { name: /^(Add an internal attachment|Ajouter une PJ interne)$/, exact: true })).toHaveCount(0)
  await page.reload()
  await expect(inline.getByRole('button', { name: 'Synthetic start · start', exact: true })).toBeVisible()
  await expect(page.locator('.document-editor-attachments .resource-preview-card')).toHaveCount(0)
  await page.locator('[data-editor-surface]').getByRole('link', { name: 'Synthetic cited execution', exact: true }).click()
  await page.keyboard.press('Alt+Enter')
  await expect(page.getByRole('dialog').getByRole('link', { name: new RegExp(`^(Copy run URL|Copier l’URL du run): ${run.id ?? run.run_id}$`) })).toHaveAttribute('href', runUri)
  await page.getByRole('dialog').getByRole('button', { name: /^(Close|Fermer)$/, exact: true }).click()
  const saved = await checked(await request.get(`/api/memory/documents/${document.id}`, { headers }))
  expect(saved.item.payload.text).toContain(processUri)
  expect(saved.item.payload.text).toContain('galaris-process-diagram')
  expect(saved.item.metadata.process_attachments ?? []).toEqual([])
  expect(await checked(await request.get(`/api/memory/documents/${document.id}/attachments?agent_id=${fixture.agent_id}`, { headers }))).toEqual([])
  expect(saved.item.payload.text).not.toContain('<svg')
  await page.screenshot({ path: test.info().outputPath('process-document-citation.png'), fullPage: true })
  expect(errors()).toEqual([])
})
