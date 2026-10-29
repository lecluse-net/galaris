import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'
import { agent, document as fixture } from './data.mjs'

for (const width of [1440, 390]) {
  test(`Data documents preserve invalid drafts and reopen saved JSON in the common editor (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    let item = { ...fixture, document_type: 'data', media_type: 'application/json', content_profile: 'document',
      title: 'Synthetic values', payload: { text: ' {"value": 1}\n' } }
    const writes = []
    await jsonRoute(page, '**/api/agents?*', [agent])
    await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice' }], users: [] })
    await jsonRoute(page, '**/api/documents/keywords?*', [])
    await jsonRoute(page, '**/api/documents/doc-a/attachments*', [])
    await page.route(/\/api\/documents\/doc-a(?:\?|$)/, async route => {
      if (route.request().method() === 'PATCH') {
        const update = route.request().postDataJSON()
        writes.push(update)
        item = { ...item, ...update, revision: item.revision + 1, lock_version: item.lock_version + 1 }
        return route.fulfill({ json: item })
      }
      return route.fulfill({ json: { item, agent_id: 7 } })
    })
    await mount(page, 'app/document/components/DocumentEditor.vue', { props: { documentId: item.id, agentId: 7 }, privileges: ['DOCUMENT_EDIT'] })
    const json = page.locator('textarea.code-editor')
    await expect(json).toHaveValue(' {"value": 1}\n')
    await json.fill('{"value":')
    await expect(page.getByText(/invalid JSON|JSON.*invalid/i)).toBeVisible()
    expect(writes).toHaveLength(0)
    await json.fill('{"value":2}')
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0].media_type).toBe('application/json')
    expect(writes[0].payload.text).toBe('{"value":2}')
    await page.evaluate(() => window.testApp.mount({ component: 'app/document/components/DocumentEditor.vue', props: { documentId: 'doc-a', agentId: 7 } }))
    await expect(json).toHaveValue('{"value":2}')
    await page.screenshot({ path: testInfo.outputPath('data-document.png'), animations: 'disabled' })
  })
}

test('New document opens the shared type menu before creating a record', async ({ page }, testInfo) => {
  const requests = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [{ id: 'folder-a', name: 'Synthetic folder', parent_id: null, position: 0, icon: null }] })
  await jsonRoute(page, '**/api/documents/library', { entries: [], total: 0, has_more: false, keywords: [], owners: [] })
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice' }], users: [] })
  await page.route('**/api/documents', route => { requests.push(route.request().postDataJSON()); return route.fulfill({ status: 500 }) })
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', { privileges: ['DOCUMENT_EDIT'] })
  await page.getByRole('button', { name: 'Create document', exact: true }).click()
  await expect(page.getByRole('menuitem', { name: 'Text', exact: true })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: 'Data', exact: true })).toBeVisible()
  await page.getByRole('menu').screenshot({ path: testInfo.outputPath('document-types.png') })
  await page.screenshot({ path: testInfo.outputPath('new-document-menu.png'), animations: 'disabled' })
  // Initial library selection can update the query while the chooser is open.
  await page.evaluate(() => window.testApp.router.replace({ query: { selection: 'synthetic' } }))
  await expect(page.getByRole('menuitem', { name: 'Data', exact: true })).toBeVisible()
  expect(requests).toHaveLength(0)
  await page.getByRole('menuitem', { name: 'Data', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  for (const name of ['Create a document at the root', 'New document in Synthetic folder']) {
    await page.getByRole('button', { name, exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('menuitem', { name: 'Data', exact: true })).toBeVisible()
    await page.getByRole('menu').screenshot({ path: testInfo.outputPath(name.startsWith('New') ? 'folder-types.png' : 'root-types.png') })
    await page.screenshot({ path: testInfo.outputPath(name.startsWith('New') ? 'folder-document-menu.png' : 'root-document-menu.png'), animations: 'disabled' })
    await page.getByRole('menuitem', { name: 'Data', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    if (name.startsWith('New')) await expect(page.getByRole('dialog')).toContainText('New document in Synthetic folder')
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  expect(requests).toHaveLength(0)
  await setPrivileges(page, ['DOCUMENT_ACCESS'])
  await expect(page.getByRole('button', { name: 'Create document', exact: true })).toHaveCount(0)
})
