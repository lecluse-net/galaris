import { selectDocumentContext, test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

async function library(page, kind = 'text') {
  const items = ['Alpha', 'Beta', 'Gamma'].map((title, index) => ({
    ...documentFixture, id: `00000000-0000-4000-8000-00000000000${index + 1}`,
    title, owner_agent_id: null, owner_user_id: 1,
    document_format: kind, media_type: kind === 'data' ? 'application/json' : 'text/html',
    content_profile: 'document', payload: { text: kind === 'data' ? JSON.stringify({ value: title }) : `<p>${title} content</p>` },
  }))
  const state = { items, refuseSave: false, writes: [] }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [] })
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await page.route('**/api/documents/library', route => route.fulfill({ json: {
    entries: state.items.map(item => ({ item, tags: [], agent_ids: [], writable_agent_ids: [], user_access: item.access })),
    total: state.items.length, has_more: false, keywords: [],
  } }))
  for (const item of items) {
    await jsonRoute(page, `**/api/documents/${item.id}/attachments*`, [])
    await page.route(new RegExp(`/api/documents/${item.id}(?:\\?|$)`), route => {
      const index = state.items.findIndex(value => value.id === item.id)
      if (route.request().method() === 'PATCH') {
        if (state.refuseSave) return route.fulfill({ status: 503, json: { detail: 'Save unavailable' } })
        const change = route.request().postDataJSON()
        state.writes.push(change)
        state.items[index] = { ...state.items[index], ...change, lock_version: state.items[index].lock_version + 1 }
        return route.fulfill({ json: state.items[index] })
      }
      return route.fulfill({ json: { item: state.items[index], agent_id: null } })
    })
  }
  return state
}

test('a mind map accepts document references from the library and uploads dropped files', async ({ page }, testInfo) => {
  const { items } = await library(page)
  const [treeSource, map, listSource] = items
  const folder = { id: 'references', name: 'Field references', parent_id: null, position: 1 }
  Object.assign(map, { document_format: 'mindmap', media_type: 'application/vnd.galaris.mindmap+json', payload: { text: JSON.stringify({
    version: 1, nodes: [{ id: 'root', parent: null, title: 'Field map' }, { id: 'inbox', parent: 'root', title: 'Drop zone' }],
  }) } })
  await jsonRoute(page, '**/api/documents/formats', ['text', 'mindmap'].map(code => ({
    code, version: 1, contract_version: 1, provider: 'galaris', storage_kind: 'text', icon: 'description',
    capabilities: { editor: 'native', preview: 'native', native_export: 'native', import: 'native' },
  })))
  await jsonRoute(page, '**/api/documents/tags', { user_id: 1, tags: [folder] })
  await page.route('**/api/documents/library', route => {
    const sources = route.request().postDataJSON().tag_id ? [treeSource] : [map, listSource]
    return route.fulfill({ json: { entries: sources.map(item => ({ item, tags: item === treeSource ? [folder] : [], agent_ids: [], writable_agent_ids: [], user_access: item.access })),
      total: sources.length, has_more: false, keywords: [] } })
  })
  const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP8/x8AAwMCAHwG0LwAAAAASUVORK5CYII='
  const file = { id: '00000000-0000-4000-8000-000000000305', name: 'sample.png', media_type: 'image/png', size_bytes: Buffer.from(png, 'base64').length }
  const imported = { ...file, id: '00000000-0000-4000-8000-000000000306', name: 'site-photo.png' }
  const imageUrl = 'https://example.org/site-photo.png'
  const attachments = []
  await page.route(new RegExp(`/api/documents/${map.id}/attachments(?:\\?|$)`), route => {
    if (route.request().method() !== 'POST') return route.fulfill({ json: attachments })
    expect(route.request().postData()).toContain('filename="sample.png"')
    attachments.push(file)
    return route.fulfill({ json: file })
  })
  await page.route(new RegExp(`/api/documents/${map.id}/import-image(?:\\?|$)`), route => {
    expect(route.request().postDataJSON()).toEqual({ url: imageUrl })
    attachments.push(imported)
    return route.fulfill({ json: imported })
  })
  for (const attachment of [file, imported]) {
    await page.route(`**/api/documents/${map.id}/attachments/${attachment.id}*`, route => route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') }))
  }
  await page.route(`**/api/documents/${map.id}`, route => {
    if (route.request().method() !== 'PATCH') return route.fulfill({ json: { item: map, agent_id: null } })
    Object.assign(map, route.request().postDataJSON(), { revision: map.revision + 1, lock_version: map.lock_version + 1 })
    return route.fulfill({ json: map })
  })
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${map.id}`, browserHistory: true, shell: true, privileges: ['DOCUMENT_EDIT'],
  })
  const target = page.getByRole('treeitem', { name: 'Drop zone', exact: true }).getByText('Drop zone', { exact: true })
  const children = () => JSON.parse(map.payload.text).nodes.filter(node => node.parent === 'inbox')
  await page.getByText(folder.name, { exact: true }).click()
  await page.locator('.document-tree').getByText(treeSource.title, { exact: true }).dragTo(target)
  await expect.poll(() => children().map(node => node.title)).toEqual([treeSource.title])
  await page.getByRole('list', { name: 'Unclassified documents', exact: true }).getByText(listSource.title, { exact: true }).dragTo(target)
  await expect.poll(() => children().map(node => node.title)).toEqual([treeSource.title, listSource.title])
  await page.getByRole('button', { name: 'Show unclassified documents as a list', exact: true }).click()
  const list = page.locator('.bulk-list')
  await list.locator('.q-item[draggable="true"]').filter({ has: page.getByRole('link', { name: listSource.title, exact: true }) }).dragTo(target)
  await expect.poll(() => children().map(node => node.title)).toEqual([treeSource.title, listSource.title, listSource.title])
  await page.screenshot({ path: testInfo.outputPath('map-and-document-list.png') })
  await list.getByRole('button', { name: 'Close list' }).click()
  for (const [index, attachment] of [file, imported].entries()) {
    const dataTransfer = await page.evaluateHandle(({ png, imageUrl, name, fromWeb }) => {
      const transfer = new DataTransfer()
      if (fromWeb) transfer.setData('text/html', `<img src="${imageUrl}" alt="${name}">`)
      else transfer.items.add(new File([Uint8Array.from(atob(png), value => value.charCodeAt(0))], name, { type: 'image/png' }))
      return transfer
    }, { png, imageUrl, name: attachment.name, fromWeb: index === 1 })
    await target.dispatchEvent('dragover', { dataTransfer })
    await target.dispatchEvent('drop', { dataTransfer })
    await expect.poll(() => children().at(-1)?.body_html).toContain(`document://${map.id}/attachments/${attachment.id}`)
    await expect(page.getByRole('img', { name: attachment.name, exact: true }).first()).toBeVisible()
    await dataTransfer.dispose()
  }
  expect(attachments.map(attachment => attachment.id)).toEqual([file.id, imported.id])
  expect(children().slice(0, 3).map(node => node.body_html)).toEqual([treeSource, listSource, listSource].map(source =>
    expect.stringContaining(`href="document://${source.id}"`)))
})

for (const width of [1440, 390]) test(`fullscreen follows document references across formats at ${width}px`, async ({ page }, testInfo) => {
  const { items } = await library(page)
  const [text, map, data] = items
  await jsonRoute(page, '**/api/documents/formats', ['text', 'mindmap', 'data'].map(code => ({
    code, version: 1, contract_version: 1, provider: 'galaris', storage_kind: 'text',
    icon: code === 'mindmap' ? 'account_tree' : 'description', qualification: 'not_run', import_extensions: [],
    capabilities: { editor: 'native', preview: 'native', native_export: 'native', import: 'native' },
  })))
  text.payload.text += `<p><a href="document://${map.id}">Open field map</a></p>`
  Object.assign(map, { document_format: 'mindmap', media_type: 'application/vnd.galaris.mindmap+json', payload: { text: JSON.stringify({
    version: 1, nodes: [{ id: 'root', parent: null, title: 'Field map' }, { id: 'data', parent: 'root', title: 'Field measurements',
      body_html: `<p><a href="document://${data.id}">Field measurements</a></p>` }],
  }) } })
  Object.assign(data, { document_format: 'data', media_type: 'application/json', payload: { text: '{"observations": 14}' } })
  await page.setViewportSize({ width, height: 900 })
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${text.id}`, browserHistory: true, shell: true, privileges: ['DOCUMENT_EDIT'],
  })

  await page.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  const fullscreen = page.locator('.document-editor--fullscreen')
  await expect.poll(() => fullscreen.evaluate(editor => {
    const frame = editor.getBoundingClientRect()
    return frame.left === 0 && frame.top === 0 && frame.width === innerWidth && frame.height === innerHeight
      && editor.contains(document.elementFromPoint(1, 120))
  })).toBe(true)
  const forward = fullscreen.getByRole('button', { name: 'Next document', exact: true })
  const back = fullscreen.getByRole('button', { name: 'Previous document', exact: true })
  const exit = fullscreen.getByRole('button', { name: 'Exit fullscreen', exact: true })
  await expect(exit).toBeVisible()
  await expect(back).toBeDisabled()
  const mapLink = fullscreen.getByRole('link', { name: 'Open field map', exact: true })
  await mapLink.click()
  await expect(fullscreen.getByRole('toolbar', { name: 'Contextual actions' })).toBeVisible()
  await expect(fullscreen.getByRole('tree')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('document-fullscreen.png'), animations: 'disabled' })
  await mapLink.click({ modifiers: ['Control'] })
  const dataLink = fullscreen.getByRole('link', { name: 'Field measurements', exact: true })
  await dataLink.click()
  await expect(fullscreen.getByRole('treeitem', { name: 'Field measurements', exact: true })).toHaveAttribute('aria-selected', 'true')
  await dataLink.click({ modifiers: ['Control'] })
  await expect(fullscreen.getByRole('textbox', { name: 'Content', exact: true })).toHaveValue('{"observations": 14}')
  await back.click()
  await expect(fullscreen.getByRole('tree')).toBeVisible()
  await forward.click()
  await expect(fullscreen.getByRole('textbox', { name: 'Content', exact: true })).toHaveValue('{"observations": 14}')
  await exit.hover()
  await expect(page.getByRole('tooltip').filter({ hasText: 'Exit fullscreen' })).toHaveCount(0)
  await exit.press('Escape')
  await expect(fullscreen).toHaveCount(0)
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(data.title)
})

for (const mobile of [false, true]) {
  for (const kind of ['text', 'data']) test(`document history follows visits, branches and skips deleted documents (${kind}, ${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
    const { items } = await library(page, kind)
    if (mobile) await page.setViewportSize({ width: 390, height: 844 })
    await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
      route: `/documents?document_id=${items[0].id}`, browserHistory: true, privileges: ['DOCUMENT_EDIT'],
    })
    const title = page.getByLabel('Title', { exact: true })
    const buttons = () => mobile ? page.getByRole('dialog') : page.locator('.page-header')
    const back = () => buttons().getByRole('button', { name: 'Previous document', exact: true })
    const forward = () => buttons().getByRole('button', { name: 'Next document', exact: true })
    const open = async item => {
      if (mobile) await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).first().click()
      await page.getByRole('list', { name: 'Unclassified documents', exact: true }).getByText(item.title, { exact: true }).click()
      await expect(title).toHaveValue(item.title)
    }
    await expect(title).toHaveValue('Alpha')
    await expect(back()).toBeDisabled()
    await expect(forward()).toBeDisabled()
    await open(items[1])
    await open(items[2])
    await page.evaluate(() => window.history.back())
    await expect(title).toHaveValue('Beta')
    await back().click()
    await expect(title).toHaveValue('Alpha')
    await expect(back()).toBeDisabled()
    await page.evaluate(() => window.history.forward())
    await expect(title).toHaveValue('Beta')
    await back().click()
    await expect(title).toHaveValue('Alpha')
    // Keyboard activation follows the same history and reads the current document.
    await forward().focus()
    await page.keyboard.press('Enter')
    await expect(title).toHaveValue('Beta')
    await open(items[0])
    await expect(forward()).toBeDisabled()
    // Reopening the current document must not create a duplicate visit.
    await open(items[0])
    await back().click()
    await expect(title).toHaveValue('Beta')
    await page.evaluate(id => window.testApp.emitSocket('document.delete', { data: { id, node_kind: 'document' } }), items[0].id)
    await expect(forward()).toBeDisabled()
    await page.screenshot({ path: testInfo.outputPath('document-navigation.png'), animations: 'disabled' })
    if (!mobile) {
      const toggleLibrary = buttons().getByRole('button', { name: 'Show or hide library', exact: true })
      await toggleLibrary.click()
      await page.screenshot({ path: testInfo.outputPath('document-library-collapsed.png'), animations: 'disabled' })
      await toggleLibrary.click()
    }
  })

  test(`document history retains edits and its position when saving fails (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
    const state = await library(page)
    state.items[0].payload.text += `<p><a href="document://${state.items[1].id}">Open Beta</a></p>`
    if (mobile) await page.setViewportSize({ width: 390, height: 844 })
    await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
      route: `/documents?document_id=${state.items[0].id}`, browserHistory: true, privileges: ['DOCUMENT_EDIT'],
    })
    const title = page.getByLabel('Title', { exact: true })
    await expect(title).toHaveValue('Alpha')
    // Opening the document uses this library's navigation, including on mobile.
    await page.getByRole('link', { name: 'Open Beta', exact: true }).click({ modifiers: ['Control'] })
    await expect(title).toHaveValue('Beta')
    await expect(page.getByRole('dialog')).toHaveCount(mobile ? 1 : 0)
    const buttons = mobile ? page.getByRole('dialog') : page.locator('.page-header')
    const back = buttons.getByRole('button', { name: 'Previous document', exact: true })
    const forward = buttons.getByRole('button', { name: 'Next document', exact: true })
    state.refuseSave = true
    await title.fill('Beta edited')
    await page.evaluate(() => window.history.back())
    await expect(page.getByText('Automatic save failed', { exact: true }).first()).toBeVisible()
    await expect(title).toHaveValue('Beta edited')
    await expect(page).toHaveURL(new RegExp(`document_id=${state.items[1].id}$`))
    await expect(back).toBeEnabled()
    await expect(forward).toBeDisabled()
    state.refuseSave = false
    await back.click()
    await expect(title).toHaveValue('Alpha')
    expect(state.writes.at(-1)).toMatchObject({ title: 'Beta edited' })
    await forward.click()
    await expect(title).toHaveValue('Beta edited')
    await expect(page.locator('[data-editor-surface]')).toContainText('Beta content')
  })
}

test('opening a library document preserves the anchor for multiple selection without changing the editor', async ({ page }) => {
  await library(page)
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', { privileges: ['DOCUMENT_EDIT'] })
  const list = page.getByRole('list', { name: 'Unclassified documents', exact: true })
  await list.getByText('Beta', { exact: true }).click()
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Beta')
  await list.getByText('Gamma', { exact: true }).click({ modifiers: ['Shift'] })
  await expect(list.locator('.document-row[aria-selected="true"]')).toHaveCount(2)
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Beta')
  await list.getByText('Alpha', { exact: true }).click({ modifiers: ['Control'] })
  await expect(list.locator('.document-row[aria-selected="true"]')).toHaveCount(3)
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Beta')
})

test('the Documents contextual dialog action leaves the library selection and history unchanged', async ({ page }) => {
  const state = await library(page)
  state.items[0].payload.text += `<p><a href="document://${state.items[1].id}">Open Beta</a></p>`
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${state.items[0].id}`, privileges: ['DOCUMENT_EDIT'],
  })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Alpha')
  await selectDocumentContext(page, page.getByRole('link', { name: 'Open Beta', exact: true }))
  await page.getByRole('button', { name: 'Open in a dialog', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Beta')
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Alpha')
  await expect(page.locator('.page-header').getByRole('button', { name: 'Previous document', exact: true })).toBeDisabled()
})

test('a dialog branch preserves the library forward action without reloading or losing its draft', async ({ page }) => {
  const state = await library(page)
  state.items[0].payload.text += `<p><a href="document://${state.items[1].id}">Open Beta</a></p>`
  state.items[1].payload.text += `<p><a href="document://${state.items[2].id}">Open Gamma</a></p>`
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${state.items[0].id}`, browserHistory: true, privileges: ['DOCUMENT_EDIT'],
  })
  const title = page.getByLabel('Title', { exact: true })
  const header = page.locator('.page-header')
  await page.getByRole('link', { name: 'Open Beta', exact: true }).click({ modifiers: ['Control'] })
  await expect(title).toHaveValue('Beta')
  await header.getByRole('button', { name: 'Previous document', exact: true }).click()
  await expect(title).toHaveValue('Alpha')
  await selectDocumentContext(page, page.getByRole('link', { name: 'Open Beta', exact: true }))
  await page.getByRole('button', { name: 'Open in a dialog', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('link', { name: 'Open Gamma', exact: true }).click({ modifiers: ['Control'] })
  await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Gamma')
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await expect(dialog).toHaveCount(0)
  await title.fill('Alpha draft after dialog')
  await header.getByRole('button', { name: 'Next document', exact: true }).click()
  await expect(title).toHaveValue('Beta')
  expect(state.writes.at(-1)).toMatchObject({ title: 'Alpha draft after dialog' })
})
