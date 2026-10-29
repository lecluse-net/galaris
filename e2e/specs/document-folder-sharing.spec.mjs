import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

// The preview contains an opaque sandboxed frame. Playwright's service-worker
// blocking script accesses navigator.serviceWorker there and raises SecurityError.
test.use({ serviceWorkers: 'allow' })

async function chooseFolder(page, name, width, agentLabel, previewFile = false) {
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: agentLabel, exact: true }).click()
  if (width < 1024) await dialog.getByRole('button', { name: /^(Show locations|Afficher les emplacements)$/, exact: true }).click()
  await dialog.getByText('document://', { exact: true }).click()
  await dialog.getByRole('main').getByRole('button', { name: /^(Open|Ouvrir) (Folders|Répertoires)$/, exact: true }).click()
  if (previewFile) {
    await dialog.getByRole('main').getByRole('button', { name: new RegExp(`^(Open|Ouvrir) ${name}$`) }).click()
    const content = page.waitForResponse(response => response.url().includes('/file-share/browser/content?'))
    await dialog.getByRole('button', { name: /^(Preview|Aperçu de) Synthetic permitted note$/, exact: true }).click()
    expect(await (await content).text()).toContain('Synthetic collection content.')
    const preview = page.locator('.fullscreen-preview')
    await expect(preview.locator('iframe')).toBeVisible()
    await preview.getByRole('button', { name: /^(Close|Fermer)$/, exact: true }).click()
    await expect(preview).toHaveCount(0)
    await dialog.getByRole('navigation', { name: /^(File navigation|Navigation des fichiers)$/, exact: true }).getByRole('button', { name: /^(Folders|Répertoires)$/, exact: true }).click()
  }
  await dialog.getByRole('checkbox', { name: new RegExp(`^(Select|Sélectionner) ${name}$`) }).check()
}

async function closeMobileDrawer(page, width) {
  const backdrop = page.locator('.q-drawer__backdrop')
  if (width < 1024 && await backdrop.isVisible()) await backdrop.click({ position: { x: width - 8, y: 150 } })
}

for (const width of [1440, 390]) test(`shared folders stay live in Documents and Chat at ${width}px`, async ({ page, request }, testInfo) => {
  test.setTimeout(90_000)
  await page.setViewportSize({ width, height: 900 })
  const errors = collectPageErrors(page)
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt => prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
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
  const agents = await checked(await request.get('/api/agents/selection', { headers, params: { scope: 'management' } }))
  const agentLabel = agents.find(agent => agent.id === fixture.agent_id).label
  const owner = (await checked(await request.get('/api/documents/tags', { headers }))).user_id
  const folder = await checked(await request.post('/api/documents/tags', { headers,
    data: { name: 'Synthetic shared collection', parent_id: null, icon: 'folder:blue' } }))
  const uri = `document://folders/${folder.id}/`
  const url = `/documents/folders/${folder.id}`
  const documents = []
  for (const title of ['Synthetic permitted note', 'Synthetic collection guide']) {
    const document = await checked(await request.post('/api/documents', { headers, data: {
      title, owner_kind: 'user', owner_id: owner, actor_agent_id: fixture.agent_id, document_type: 'html', folder: '',
    } }))
    await checked(await request.patch(`/api/documents/${document.id}`, { headers, data: {
      expected_revision: document.revision, payload: { text: '<p>Synthetic collection content.</p>' },
    } }))
    documents.push(document)
  }
  const assigned = await request.put(`/api/documents/${documents[0].id}/tags`, { headers, data: { tag_id: folder.id } })
  expect(assigned.ok(), await assigned.text()).toBeTruthy()
  const folderPath = `/api/documents/folder-collections/${folder.id}`
  expect((await request.get(folderPath, { headers, params: { agent_id: fixture.agent_id } })).status()).toBe(404)
  let sharing = await checked(await request.get(`/api/documents/tags/${folder.id}/sharing`, { headers }))
  await checked(await request.put(`/api/documents/tags/${folder.id}/sharing`, { headers, data: {
    level: 'private', can_write: false, expected_lock_version: sharing.lock_version,
    grants: [{ kind: 'agent', id: fixture.agent_id, can_write: false }],
  } }))
  const agentView = await checked(await request.get(folderPath, { headers, params: { agent_id: fixture.agent_id } }))
  expect(agentView.entries.map(entry => entry.uri)).toContain(`document://${documents[0].id}`)
  await page.goto(`/documents?document_id=${documents[1].id}`)
  await page.getByRole('button', { name: /^(Galaris link|Lien Galaris)$/, exact: true }).click()
  await chooseFolder(page, folder.name, width, agentLabel, true)
  const saved = page.waitForResponse(response => response.url().includes(`/api/documents/${documents[1].id}`) && response.request().method() === 'PATCH')
  await page.getByRole('dialog').getByRole('button', { name: /^(Select|Sélectionner)$/, exact: true }).click()
  expect((await saved).ok()).toBeTruthy()
  await expect(page.locator('.internal-file-picker')).toHaveCount(0)
  await expect(page.locator('.folder-citation-thumbnail')).toBeVisible()
  await page.reload()
  await expect(page.locator('.folder-citation-thumbnail')).toBeVisible()
  const carrier = await checked(await request.get(`/api/documents/${documents[1].id}`, { headers }))
  expect(carrier.item.payload.text).toContain(uri)
  expect(carrier.item.payload.text).toContain('Synthetic collection content.')
  expect(carrier.item.payload.text).not.toContain('data:image')
  await page.screenshot({ path: testInfo.outputPath('folder-in-document.png'), fullPage: true, animations: 'disabled' })
  await errors.settle()
  await page.goto(url)
  await expect(page.getByRole('heading', { name: folder.name, exact: true })).toBeVisible()
  await closeMobileDrawer(page, width)
  await page.getByText('Synthetic permitted note', { exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Synthetic collection content.')
  await page.getByRole('dialog').getByRole('button', { name: /^(Close|Fermer)$/, exact: true }).click()
  await errors.settle()
  await page.goto(`/chat?room=${fixture.rooms[0]}`)
  const composer = page.locator('.composer-shell')
  await expect(composer.locator('textarea')).toBeVisible()
  await closeMobileDrawer(page, width)
  if (width < 1024) {
    await composer.getByRole('button', { name: /^(Add attachments|Ajouter des pièces jointes)$/, exact: true }).click()
    await page.getByText(/^(Add an internal attachment|Ajouter une PJ interne)$/, { exact: true }).click()
  } else await composer.getByRole('button', { name: /^(Add an internal attachment|Ajouter une PJ interne)$/, exact: true }).click()
  await chooseFolder(page, folder.name, width, agentLabel)
  await page.getByRole('dialog').getByRole('button', { name: /^(Select|Sélectionner)$/, exact: true }).click()
  const input = page.locator('.composer-fields textarea')
  await expect(input).toHaveValue('')
  await expect(composer.locator('.attachment-list')).toContainText(folder.name)
  await composer.getByRole('button', { name: /^(Post|Poster)$/, exact: true }).click()
  const preview = page.locator('.resource-preview-block').filter({ hasText: folder.name }).first()
  await expect(preview).toBeVisible()
  await preview.getByRole('button', { name: new RegExp(folder.name) }).first().click()
  await expect(page.getByRole('dialog').getByText('Synthetic permitted note', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('folder-in-chat.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('dialog').getByRole('button', { name: /^(Close|Fermer)$/, exact: true }).click()
  sharing = await checked(await request.get(`/api/documents/tags/${folder.id}/sharing`, { headers }))
  await checked(await request.put(`/api/documents/tags/${folder.id}/sharing`, { headers, data: {
    level: 'private', can_write: false, expected_lock_version: sharing.lock_version, grants: [],
  } }))
  expect((await request.get(folderPath, { headers, params: { agent_id: fixture.agent_id } })).status()).toBe(404)
  await request.post(`/api/__test/release/${fixture.rooms[0]}`)
  await errors.settle()
  expect(errors()).toEqual([])
})
