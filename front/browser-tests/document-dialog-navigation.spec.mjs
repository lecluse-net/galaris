import { selectDocumentContext, test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

async function documents(page) {
  const ids = [1, 2, 3].map(index => `00000000-0000-4000-8000-00000000000${index}`)
  const items = ['Alpha', 'Beta', 'Gamma'].map((title, index) => ({
    ...documentFixture, id: ids[index], title, owner_agent_id: index === 0 ? 7 : null,
    owner_user_id: index === 0 ? null : 1, media_type: 'text/html', content_profile: 'document',
    payload: { text: `<p>${title} content</p>` },
  }))
  items[0].payload.text += `<p><a href="document://${ids[1]}">Open Beta</a></p>`
  items[1].payload.text += `<blockquote class="galaris-link-card"><p><a href="document://${ids[2]}">Open Gamma</a></p><p>Gamma card summary</p></blockquote><p><a href="document://${ids[0]}">Open Alpha</a></p>`
  const state = { items, refuseSave: false, writes: [], reads: [] }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  for (const item of items) {
    await jsonRoute(page, `**/api/documents/${item.id}/attachments*`, [])
    await page.route(new RegExp(`/api/documents/${item.id}(?:\\?|$)`), route => {
      const index = state.items.findIndex(value => value.id === item.id)
      const actor = new URL(route.request().url()).searchParams.get('agent_id')
      if (index !== 0 && actor) return route.fulfill({ status: 403, json: { detail: 'Private User document' } })
      if (route.request().method() === 'PATCH') {
        if (state.refuseSave) return route.fulfill({ status: 503, json: { detail: 'Save unavailable' } })
        const change = route.request().postDataJSON()
        state.writes.push(change)
        state.items[index] = { ...state.items[index], ...change, lock_version: state.items[index].lock_version + 1 }
        return route.fulfill({ json: state.items[index] })
      }
      state.reads.push({ id: item.id, actor })
      return route.fulfill({ json: { item: state.items[index], agent_id: index === 0 ? 7 : null } })
    })
  }
  return state
}

for (const width of [1440, 390]) {
  test(`document dialogs keep links, cards and history inside the window at ${width}px`, async ({ page }, testInfo) => {
    const state = await documents(page)
    const editable = width === 1440
    await page.setViewportSize({ width, height: 900 })
    await mount(page, 'app/chat/components/ConversationDocumentDialog.vue', {
      route: '/chat', browserHistory: true, props: { modelValue: true, documentId: state.items[0].id, agentId: 7, title: 'Alpha', editable }, privileges: ['DOCUMENT_EDIT'],
    })
    const dialog = page.getByRole('dialog')
    const title = dialog.getByLabel('Title', { exact: true })
    const back = dialog.getByRole('button', { name: 'Previous document', exact: true })
    const forward = dialog.getByRole('button', { name: 'Next document', exact: true })
    const open = async name => dialog.getByRole('link', { name, exact: true }).click({ modifiers: ['Control'] })
    await expect(title).toHaveValue('Alpha')
    await expect(back).toBeDisabled()
    await expect(forward).toBeDisabled()
    async function findInDocument(text) {
      await dialog.locator('[data-editor-surface]').click()
      await page.keyboard.press('Control+f')
      const search = dialog.getByRole('search', { name: 'Find', exact: true })
      const input = search.getByRole('textbox', { name: 'Find', exact: true })
      await expect(input).toBeFocused()
      await input.fill(text)
      await input.press('Enter')
      await expect(dialog.locator('[data-search-current]')).toHaveText(text)
      await expect(dialog).toHaveCount(1)
      await input.press('Escape')
      await expect(search).toBeHidden()
      await expect(dialog).toBeVisible()
    }
    await findInDocument('Alpha content')
    await open('Open Beta')
    await expect(title).toHaveValue('Beta')
    await findInDocument('Beta content')
    await open('Open Gamma')
    await expect(title).toHaveValue('Gamma')
    await page.evaluate(() => window.history.back())
    await expect(title).toHaveValue('Beta')
    await back.focus()
    await page.keyboard.press('Enter')
    await expect(title).toHaveValue('Alpha')
    await page.evaluate(() => window.history.forward())
    await expect(title).toHaveValue('Beta')
    await open('Open Alpha')
    await expect(title).toHaveValue('Alpha')
    await expect(forward).toBeDisabled()
    await expect(dialog).toHaveCount(1)
    expect(state.reads.filter(read => read.id === state.items[0].id).every(read => read.actor === '7')).toBe(true)
    expect(state.reads.filter(read => read.id !== state.items[0].id).every(read => read.actor === null)).toBe(true)
    expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/chat')
    await back.hover()
    await expect(page.getByRole('tooltip')).toHaveText('Previous document')
    await page.screenshot({ path: testInfo.outputPath('document-dialog-navigation.png'), animations: 'disabled' })
    if (width === 1440) {
      await page.evaluate(() => window.testApp.dark(true))
      await page.screenshot({ path: testInfo.outputPath('document-dialog-navigation-dark.png'), animations: 'disabled' })
    }
    if (width === 1440) await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
    else await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
    await expect(dialog).toHaveCount(0)
    await page.evaluate(() => window.testApp.setProps({ modelValue: true }))
    await expect(title).toHaveValue('Alpha')
    await expect(back).toBeDisabled()
    await expect(forward).toBeDisabled()
  })
}

test('modal navigation preserves unsaved changes after refusal and edits made while a destination loads', async ({ page }) => {
  const state = await documents(page)
  await mount(page, 'core/util/components/WorkingDocumentDialog.vue', {
    route: '/chat', browserHistory: true, props: { modelValue: true, documentId: state.items[0].id, agentId: 7, editable: true }, privileges: ['DOCUMENT_EDIT'],
  })
  const dialog = page.getByRole('dialog')
  const title = dialog.getByLabel('Title', { exact: true })
  const link = dialog.getByRole('link', { name: 'Open Beta', exact: true })
  await expect(title).toHaveValue('Alpha')
  state.refuseSave = true
  await title.fill('Alpha draft')
  await link.click({ modifiers: ['Control'] })
  await expect(page.getByText('Automatic save failed', { exact: true }).first()).toBeVisible()
  await expect(title).toHaveValue('Alpha draft')
  await expect(dialog.getByRole('button', { name: 'Previous document', exact: true })).toBeDisabled()
  state.refuseSave = false
  let release, started = false
  const gate = new Promise(resolve => { release = resolve })
  await page.route(new RegExp(`/api/documents/${state.items[1].id}(?:\\?|$)`), async route => {
    started = true; await gate; return route.fallback()
  })
  await link.click({ modifiers: ['Control'] })
  try {
    await expect.poll(() => started).toBe(true)
    await title.fill('Alpha edited during loading')
  } finally { release() }
  await expect(title).toHaveValue('Beta')
  expect(state.writes.at(-1)).toMatchObject({ title: 'Alpha edited during loading' })
  state.refuseSave = true
  await title.fill('Beta draft')
  await page.evaluate(() => window.history.back())
  await expect(page.getByText('Automatic save failed', { exact: true }).first()).toBeVisible()
  await expect(title).toHaveValue('Beta draft')
  await expect(dialog.getByRole('button', { name: 'Next document', exact: true })).toBeDisabled()
  state.refuseSave = false
  await dialog.getByRole('button', { name: 'Previous document', exact: true }).click()
  await expect(title).toHaveValue('Alpha edited during loading')
})

test('a denied destination keeps the current document and closing discards a late response', async ({ page }) => {
  const state = await documents(page)
  let release, started = false, mode = 'denied'
  const gate = new Promise(resolve => { release = resolve })
  await page.route(new RegExp(`/api/documents/${state.items[1].id}(?:\\?|$)`), async route => {
    if (mode === 'denied') return route.fulfill({ status: 403, json: { detail: 'Access denied' } })
    started = true; await gate; return route.fallback()
  })
  await mount(page, 'core/util/components/WorkingDocumentDialog.vue', {
    route: '/chat', props: { modelValue: true, documentId: state.items[0].id, agentId: 7 },
  })
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('link', { name: 'Open Beta', exact: true }).click({ modifiers: ['Control'] })
  await expect(page.getByText('Documents could not be loaded.', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Alpha')
  mode = 'late'
  await dialog.getByRole('link', { name: 'Open Beta', exact: true }).click({ modifiers: ['Control'] })
  try {
    await expect.poll(() => started).toBe(true)
    await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
    await expect(dialog).toHaveCount(0)
  } finally { release() }
  await page.evaluate(() => window.testApp.setProps({ modelValue: true }))
  await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Alpha')
  await expect(dialog.getByRole('button', { name: 'Previous document', exact: true })).toBeDisabled()
})

test('opening a separate dialog from a document dialog preserves each navigation context', async ({ page }) => {
  const state = await documents(page)
  await mount(page, 'core/util/components/WorkingDocumentDialog.vue', {
    route: '/chat', browserHistory: true, props: { modelValue: true, documentId: state.items[0].id, agentId: 7, editable: true }, privileges: ['DOCUMENT_EDIT'],
  })
  const parent = page.getByRole('dialog').first()
  await expect(parent.getByLabel('Title', { exact: true })).toHaveValue('Alpha')
  await selectDocumentContext(page, parent.getByText('Open Beta', { exact: true }))
  await page.getByRole('button', { name: 'Open in a dialog', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(2)
  const child = page.getByRole('dialog').nth(1)
  await expect(child.getByLabel('Title', { exact: true })).toHaveValue('Beta')
  // Read-only cards open directly in their current navigation context.
  await child.getByText('Gamma card summary', { exact: true }).click()
  await expect(child.getByLabel('Title', { exact: true })).toHaveValue('Gamma')
  await expect(page.getByRole('dialog')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Open in a dialog', exact: true })).toBeHidden()
  await page.evaluate(() => window.history.back())
  await expect(child.getByLabel('Title', { exact: true })).toHaveValue('Beta')
  await child.getByRole('link', { name: 'Open Alpha', exact: true }).click({ modifiers: ['Control'] })
  await expect(child.getByLabel('Title', { exact: true })).toHaveValue('Alpha')
  await child.getByRole('button', { name: 'Previous document', exact: true }).click()
  await expect(child.getByLabel('Title', { exact: true })).toHaveValue('Beta')
  await expect(parent.getByRole('button', { name: 'Previous document', exact: true })).toBeDisabled()
  expect(await page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/chat')
})

test('rapid browser traversal ignores a late document without rolling back the latest visit', async ({ page }) => {
  const state = await documents(page)
  await mount(page, 'core/util/components/WorkingDocumentDialog.vue', {
    route: '/chat', browserHistory: true,
    props: { modelValue: true, documentId: state.items[0].id, agentId: 7 },
  })
  const dialog = page.getByRole('dialog')
  const title = dialog.getByLabel('Title', { exact: true })
  await dialog.getByRole('link', { name: 'Open Beta', exact: true }).click({ modifiers: ['Control'] })
  await expect(title).toHaveValue('Beta')
  await dialog.getByRole('link', { name: 'Open Gamma', exact: true }).click({ modifiers: ['Control'] })
  await expect(title).toHaveValue('Gamma')
  let release, started = false, finished = false
  const gate = new Promise(resolve => { release = resolve })
  await page.route(new RegExp(`/api/documents/${state.items[1].id}(?:\\?|$)`), async route => {
    started = true
    await gate
    await route.fallback()
    finished = true
  })
  await page.evaluate(() => window.history.back())
  try {
    await expect.poll(() => started).toBe(true)
    await page.evaluate(() => window.history.back())
    await expect(title).toHaveValue('Alpha')
  } finally { release() }
  await expect.poll(() => finished).toBe(true)
  await expect(title).toHaveValue('Alpha')
  // The native cursor must still be on Alpha: forward restores Beta, not Gamma.
  await page.evaluate(() => window.history.forward())
  await expect(title).toHaveValue('Beta')
})
