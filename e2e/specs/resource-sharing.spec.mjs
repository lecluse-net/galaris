import { test, expect } from '@playwright/test'
import { collectPageErrors } from '../page-errors.mjs'

async function checked(response) {
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

async function login(page, credentials) {
  page.setDefaultTimeout(20_000)
  await page.addLocatorHandler(page.locator('.chat-notification-prompt'), prompt =>
    prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(credentials.email)
  await page.locator('input[type=password]').fill(credentials.password)
  const authenticated = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const session = await checked(await authenticated)
  await expect(page.locator('input[type=password]')).toHaveCount(0)
  return { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
}

for (const kind of ['document', 'process']) test(`${kind} sharing survives reopening, grants editing without resharing and revokes access`, async ({ page, request, browser }) => {
  test.setTimeout(120_000)
  const owner = await checked(await request.post('/api/__test/seed'))
  const ownerErrors = collectPageErrors(page)
  const headers = await login(page, owner)
  // Processes use the page under the mobile drawer; Documents use a dialog
  // above it. Do not try to dismiss an underlying drawer through that dialog.
  if (kind === 'process') await page.addLocatorHandler(page.locator('.q-drawer__backdrop'), backdrop =>
    backdrop.click({ position: { x: 380, y: 150 } }))
  const suffix = `${kind}-${owner.agent_id}`
  const credentials = { email: `synthetic-sharing-${suffix}@example.com`, password: 'Synthetic-sharing-password-42!' }
  const recipient = await checked(await request.post('/api/auth/users', { headers, data: {
    ...credentials, display_name: `Synthetic recipient ${suffix}`, language: 'fr', is_active: true,
  } }))
  const role = await checked(await request.post('/api/authorize/roles', { headers,
    data: { code: `synthetic-sharing-${suffix}`, display_name: 'Synthetic resource editor' } }))
  const privileges = await checked(await request.get('/api/authorize/privileges', { headers }))
  const allowed = new Set(['user', 'MEMORY_ACCESS', 'MEMORY_EDIT', 'PROCESS_READ', 'PROCESS_EDIT', 'AGENT_ACCESS', 'CHAT_ACCESS'])
  await checked(await request.post(`/api/authorize/roles/${role.id}/privileges`, { headers,
    data: { privilege_ids: privileges.filter(privilege => allowed.has(privilege.code)).map(privilege => privilege.id) } }))
  await checked(await request.post('/api/authorize/assignments', { headers,
    data: { user_id: recipient.id, role_id: role.id, is_default: true } }))
  let resource, api, sharingApi, path
  if (kind === 'document') {
    resource = await checked(await request.post('/api/memory/items', { headers, data: {
      owner_agent_id: owner.agent_id, title: `Synthetic shared ${suffix}`, node_kind: 'document',
      media_type: 'text/html', payload: { text: '<p>Synthetic content retained through sharing.</p>' },
    } }))
    api = `/api/memory/documents/${resource.id}`
    sharingApi = `${api}/sharing-level`
    path = `/documents?document_id=${resource.id}`
  } else {
    resource = await checked(await request.post('/api/processes/internal/definitions', { headers, data: {
      agent_id: owner.agent_id, title: `Synthetic shared ${suffix}`, owner: 'user', graph: {
        schema_version: 'galaris.bpmn/v1', actors: [{ id: 'executor', name: 'Synthetic executor', kind: 'agent', agent_id: owner.agent_id }],
        nodes: [{ id: 'start', kind: 'start' }, { id: 'work', kind: 'task', title: 'Synthetic work', config: {
          actor: 'executor', prompt: 'Retain these synthetic instructions.',
        } }, { id: 'end', kind: 'end' }],
        flows: [{ id: 'first', source: 'start', target: 'work' }, { id: 'last', source: 'work', target: 'end' }],
      },
    } }))
    api = `/api/processes/internal/definitions/${resource.code}`
    sharingApi = `${api}/sharing`
    path = `/process/internal/${resource.code}`
  }
  const context = await browser.newContext()
  const reader = await context.newPage()
  const readerErrors = collectPageErrors(reader)
  try {
    const readerHeaders = await login(reader, credentials)
    const denied = await request.get(api, { headers: readerHeaders })
    expect([403, 404]).toContain(denied.status())
    await page.goto(path)
    const sharing = page.getByRole('combobox', { name: /^(Partage|Sharing)$/, exact: true })
    await expect(sharing).toContainText(/Privé|Private/)
    await sharing.press('Enter')
    const saved = page.waitForResponse(response => new URL(response.url()).pathname === sharingApi && response.request().method() === 'PUT')
    await page.getByRole('button', { name: `${recipient.display_name} : Lecture`, exact: true }).click()
    expect((await saved).ok()).toBeTruthy()
    await page.keyboard.press('Escape')
    await expect(sharing).toContainText(recipient.display_name)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await expect(sharing).toContainText(recipient.display_name)
    await reader.goto(path)
    const original = await checked(await request.get(api, { headers: readerHeaders }))
    expect(kind === 'document' ? original.item.access.can_write : original.can_write).toBe(false)
    const title = reader.getByRole('textbox', { name: /^(Titre|Title)$/, exact: true })
    await expect(title).toHaveValue(resource.title)
    await expect(title).not.toBeEditable()
    const toggle = page.getByRole('button', { name: `Basculer lecture / écriture pour ${recipient.display_name}`, exact: true })
    const edited = page.waitForResponse(response => new URL(response.url()).pathname === sharingApi && response.request().method() === 'PUT')
    await toggle.click()
    expect((await edited).ok()).toBeTruthy()
    await reader.reload()
    await expect(title).toBeEditable()
    const writable = await checked(await request.get(api, { headers: readerHeaders }))
    expect(kind === 'document' ? writable.item.access.can_write : writable.can_write).toBe(true)
    const editedTitle = `${resource.title} edited by recipient`
    const persisted = reader.waitForResponse(response => new URL(response.url()).pathname === api
      && response.request().method() === (kind === 'document' ? 'PATCH' : 'PUT'))
    await title.fill(editedTitle)
    if (kind === 'document') await title.press('Tab')
    else await reader.getByRole('button', { name: /^(Enregistrer|Save)$/, exact: true }).click()
    expect((await persisted).ok()).toBeTruthy()
    const modified = await checked(await request.get(api, { headers }))
    expect(kind === 'document' ? modified.item.title : modified.title).toBe(editedTitle)
    const state = await checked(await request.get(`${api}/sharing`, { headers: readerHeaders }))
    expect(state.can_manage).toBe(false)
    const reshare = await request.put(sharingApi, { headers: readerHeaders,
      data: { level: 'public', can_write: true, grants: [], expected_lock_version: state.lock_version } })
    expect([403, 404]).toContain(reshare.status())
    // The content edit advanced the resource version in another session.
    await page.reload()
    await expect(sharing).toContainText(recipient.display_name)
    const revoked = page.waitForResponse(response => new URL(response.url()).pathname === sharingApi && response.request().method() === 'PUT')
    await page.getByRole('button', { name: `Retirer l’accès de ${recipient.display_name}`, exact: true }).click()
    expect((await revoked).ok()).toBeTruthy()
    const inaccessible = await request.get(api, { headers: readerHeaders })
    expect([403, 404]).toContain(inaccessible.status())
    await reader.goto('/user/profile')
    const reopened = reader.waitForResponse(response => new URL(response.url()).pathname === api)
    await reader.goto(path)
    expect([403, 404]).toContain((await reopened).status())
    const retained = await checked(await request.get(api, { headers }))
    if (kind === 'document') expect(retained.item.payload.text).toContain('Synthetic content retained through sharing.')
    else expect(retained.graph.nodes.find(node => node.id === 'work').config.prompt).toBe('Retain these synthetic instructions.')
    expect(ownerErrors()).toEqual([])
    expect(readerErrors()).toEqual([])
  } finally {
    await context.close()
  }
})
