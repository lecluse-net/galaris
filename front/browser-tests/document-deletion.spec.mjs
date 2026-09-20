import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

for (const [locale, label] of [['fr', 'Document supprimé'], ['en', 'Document deleted']]) {
  test(`chat keeps the old document title after deletion and reopening (${locale})`, async ({ page }) => {
    const id = '00000000-0000-4000-8000-000000000001'
    let deleted = false
    await page.route('**/api/chat/rooms/room-a/messages/message-a/previews', route => route.fulfill({ json: [{
      uri: `document://${id}`, kind: 'document', title: 'Rapport annuel', deleted,
      content: deleted ? null : '<p>Previous contents</p>', description: '', metadata: {},
      content_format: deleted ? 'none' : 'html', open_mode: 'inline', image_available: false, download_available: false,
    }] }))
    const options = { props: { roomId: 'room-a', messageId: 'message-a' }, locale }
    await mount(page, 'app/chat/components/MessageResourcePreviews.vue', options)
    const card = page.getByRole('article').filter({ hasText: 'Rapport annuel' })
    await expect(card.getByRole('button').first()).toBeVisible()
    deleted = true
    await page.evaluate(id => window.testApp.emitSocket('memory.delete', { data: { id, node_kind: 'document' } }), id)
    await expect(card).toContainText(label)
    await expect(card.getByRole('button')).toHaveCount(0)
    await card.click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await mount(page, 'app/chat/components/MessageResourcePreviews.vue', {
      ...options, props: { ...options.props, canReadDocuments: true, canEditDocuments: true },
    })
    await expect(card).toContainText(label)
    await expect(card.getByRole('button')).toHaveCount(0)
  })
}

async function setup(page, { human = false, item = {}, privileges = ['MEMORY_EDIT'], editable = true } = {}) {
  let document = { ...documentFixture, media_type: 'text/html', content_profile: 'document',
    payload: { text: '<p>Keep my content</p>' },
    ...(human ? { owner_agent_id: null, owner_user_id: 1 } : {}), ...item }
  const requests = []
  const state = { fail: false }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/memory/documents/owner-options?*', {
    agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '' }],
    users: [{ id: 1, kind: 'user', label: 'Me', subtitle: '', is_current_user: true }],
  })
  await jsonRoute(page, '**/api/memory/documents/keywords?*', [])
  await page.route(/\/api\/memory\/documents\/doc-a\/attachments(?:\?|$)/, route => route.fulfill({ json: [] }))
  await page.route(/\/api\/memory\/(?:items|documents)\/doc-a(?:\?|$)/, route => {
    const request = route.request()
    if (request.method() === 'DELETE') {
      requests.push(request)
      return route.fulfill(state.fail ? { status: 403, json: { detail: 'Access denied' } } : { json: {} })
    }
    if (request.method() !== 'GET') document = { ...document, ...request.postDataJSON(), revision: document.revision + 1 }
    return route.fulfill({ json: human && request.method() === 'GET' ? { item: document, agent_id: null } : document })
  })
  await mount(page, 'app/memory/components/DocumentEditor.vue', {
    props: { documentId: 'doc-a', agentId: human ? null : 7, editable }, privileges,
  })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(document.title)
  return { requests, state }
}

for (const human of [false, true]) {
  test(`${human ? 'human' : 'agent'} owner confirms deletion, can cancel, and can retry a refused deletion`, async ({ page }) => {
    const { requests, state } = await setup(page, { human })
    const button = page.getByRole('button', { name: 'Delete document', exact: true })
    await button.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Test document')
    expect(requests).toHaveLength(0)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(requests).toHaveLength(0)
    await button.click()
    await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
    await expect(dialog).toHaveCount(0)
    expect(requests).toHaveLength(0)
    await button.click()
    state.fail = true
    await dialog.getByRole('button', { name: 'Delete document', exact: true }).click()
    await expect(page.getByText('Unable to delete the document.', { exact: true })).toBeVisible()
    await expect(page.locator('.ck-editor__editable')).toContainText('Keep my content')
    state.fail = false
    await dialog.getByRole('button', { name: 'Delete document', exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'unavailable').map(event => event.value))).toEqual(['doc-a'])
    await expect(dialog).toHaveCount(0)
    expect(requests).toHaveLength(2)
    expect(new URL(requests[1].url()).searchParams.get('actor_agent_id')).toBe(human ? null : '7')
  })
}

for (const [name, options] of [
  ['shared with an agent, even for an administrator', { item: { owner_agent_id: 99 }, privileges: ['MEMORY_EDIT', 'MEMORY_ADMIN'] }],
  ['shared with a human', { human: true, item: { owner_user_id: 99 } }],
  ['without the delete privilege', { privileges: [] }],
  ['protected', { item: { deletion_protected: true } }],
  ['source managed', { item: { source_managed: true } }],
  ['read-only editor', { editable: false }],
]) {
  test(`no deletion action for a document ${name}`, async ({ page }) => {
    const { requests } = await setup(page, options)
    await expect(page.getByRole('button', { name: 'Delete document', exact: true })).toHaveCount(0)
    expect(requests).toHaveLength(0)
  })
}

for (const mobile of [false, true]) {
  test(`deleting a personal document removes it from the ${mobile ? 'mobile' : 'desktop'} library`, async ({ page }) => {
    await setup(page, { human: true })
    if (mobile) await page.setViewportSize({ width: 390, height: 844 })
    let deleted = false
    const item = { ...documentFixture, owner_agent_id: null, owner_user_id: 1 }
    await jsonRoute(page, '**/api/memory/documents/tags', { user_id: 1, tags: [] })
    await page.route('**/api/memory/documents/library', route => route.fulfill({ json: {
      entries: deleted ? [] : [{ item, tags: [], agent_ids: [], writable_agent_ids: [], user_access: item.access }],
      total: deleted ? 0 : 1, has_more: false, keywords: [],
    } }))
    await page.route('**/api/memory/items/doc-a', async route => {
      expect(route.request().method()).toBe('DELETE')
      deleted = true
      // The real server can notify readers before the HTTP response reaches the caller.
      await page.evaluate(() => window.testApp.emitSocket('memory.delete', { data: { id: 'doc-a', node_kind: 'document' } }))
      await route.fulfill({ json: {} })
    })
    await mount(page, 'app/memory/components/DocumentLibraryPage.vue', { privileges: ['MEMORY_EDIT'] })
    if (mobile) await page.getByText('Test document', { exact: true }).click()
    await page.getByRole('button', { name: 'Delete document', exact: true }).click()
    const confirmation = page.getByRole('dialog').filter({ hasText: 'Permanently delete' })
    await confirmation.getByRole('button', { name: 'Delete document', exact: true }).click()
    await expect.poll(() => deleted).toBe(true)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByText('Test document', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('list', { name: 'Unclassified documents', exact: true })).toContainText('No document matches this search.')
    // Mobile returns to the library; only desktop has an empty editor pane.
    if (!mobile) await expect(page.getByText('Select a document in the tree.', { exact: true })).toBeVisible()
  })
}
