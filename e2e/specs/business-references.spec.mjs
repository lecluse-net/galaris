import { createDocument } from '../documents.mjs'
import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

test('activity and topic references persist as compact cards and open modals after reloading a document', async ({ page, request, context, browserName }) => {
  if (browserName === 'chromium') await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  else {
    let clipboardText = ''
    await context.exposeBinding('__fixtureClipboardWrite', (_source, text) => { clipboardText = text })
    await context.exposeBinding('__fixtureClipboardRead', () => clipboardText)
    await page.addInitScript(() => {
      // Firefox/WebKit do not expose Chromium's clipboard permissions. Replace
      // only the OS boundary; the copy action and editor paste handling stay real.
      Object.defineProperty(navigator, 'clipboard', { value: {
        writeText: value => window.__fixtureClipboardWrite(value), readText: () => window.__fixtureClipboardRead(),
      } })
    })
  }
  const errors = collectPageErrors(page)
  const fixture = await (await request.post('/api/__test/seed')).json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(fixture.email)
  await page.locator('input[type=password]').fill(fixture.password)
  const authenticated = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await (await authenticated).json()
  const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
  async function checked(response) { expect(response.ok(), await response.text()).toBeTruthy(); return response.json() }
  const topic = await checked(await request.post('/api/topics', { headers, data: { title: 'Synthetic reference dossier', description: 'Dossier details', keywords: [] } }))
  const task = await checked(await request.post('/api/tasks', { headers, data: {
    label: 'Synthetic reference work', objective: '<p>Full objective kept outside the card</p>', agent_id: fixture.agent_id,
    status: 'SUCCESS', topic_id: topic.id,
  } }))
  const document = await checked(await createDocument(request, { headers, data: {
    owner_agent_id: fixture.agent_id, title: 'Synthetic reference report', node_kind: 'document', media_type: 'text/html',
    payload: { text: '<p>Preserve authored content</p>' },
  } }))
  await errors.settle()
  await page.goto(`/task?task_id=${task.id}`)
  await expect(page.getByRole('dialog').locator('.task-detail')).toContainText('Full objective kept outside the card')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.goto('/task?tab=tasks')
  const row = page.locator('.active-task-row').filter({ hasText: task.label })
  await expect(row).toBeVisible()
  await row.click({ button: 'right' })
  await page.getByRole('menuitem', { name: /^(Copy reference|Copier la référence)$/ }).click()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(`galaris://task/${task.id}`)
  await page.goto(`/documents?document_id=${document.id}`)
  const editor = page.locator('[data-editor-surface]')
  await expect(editor).toContainText('Preserve authored content')
  await editor.click(); await page.keyboard.press('Control+End'); await page.keyboard.press('Enter')
  if (browserName === 'chromium') await page.keyboard.press('Control+v')
  else {
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(`galaris://task/${task.id}`)
    await editor.evaluate(async element => {
      const clipboardData = new DataTransfer()
      clipboardData.setData('text/plain', await navigator.clipboard.readText())
      element.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true }))
    })
  }
  await expect(editor.locator('a')).toHaveText(task.label)
  await editor.locator('a').evaluate(element => {
    const range = document.createRange(); range.selectNodeContents(element)
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
  const save = () => page.waitForResponse(response => new URL(response.url()).pathname === `/api/documents/${document.id}` && response.request().method() === 'PATCH')
  const cardSaved = save()
  await page.getByRole('button', { name: /^(Show card|Afficher une carte)$/ }).click()
  const card = editor.locator('.galaris-link-card')
  await expect(card).toContainText(task.label)
  await expect(card).not.toContainText('Full objective')
  expect((await cardSaved).ok()).toBeTruthy()
  await page.reload()
  await expect(card).toContainText(task.label)
  const route = page.url()
  await card.locator('a').click()
  await expect(page.getByRole('dialog').locator('.task-detail')).toContainText('Full objective kept outside the card')
  expect(page.url()).toBe(route)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  // The toolbar finds the actual Topic API object and inserts it without a file copy.
  await editor.locator('p').first().click(); await page.keyboard.press('Home')
  await page.getByRole('button', { name: /^(Galaris link|Lien Galaris)$/ }).click()
  await page.getByRole('tab', { name: /^(Galaris objects|Objets Galaris)$/ }).click()
  await page.getByRole('textbox', { name: /Search Galaris objects|Rechercher un objet Galaris/ }).fill(topic.title)
  const topicSaved = save()
  await page.getByRole('dialog').getByText(topic.title, { exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const topicLink = editor.getByRole('link', { name: topic.title, exact: true })
  await expect(topicLink).toBeVisible()
  expect((await topicSaved).ok()).toBeTruthy()
  const persisted = await checked(await request.get(`/api/documents/${document.id}`, { headers }))
  expect(persisted.item.payload.text).toContain(`galaris://task/${task.id}`)
  expect(persisted.item.payload.text).toContain(`galaris://topic/${topic.id}`)
  await page.reload()
  await expect(topicLink).toBeVisible()
  await topicLink.click(); await page.keyboard.press('Alt+Enter')
  await expect(page.getByRole('dialog').getByRole('tab', { name: /^(Tasks|Tâches)$/ })).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText('Dossier details')
  expect(page.url()).toBe(route)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/documents?document_id=${document.id}`)
  await expect(card).toBeVisible()
  await card.screenshot({ path: test.info().outputPath('task-reference-mobile.png') })
  await errors.settle()
})
