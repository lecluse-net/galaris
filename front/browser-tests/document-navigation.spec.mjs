import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document as documentFixture } from './data.mjs'

async function library(page) {
  const items = ['Alpha', 'Beta', 'Gamma'].map((title, index) => ({
    ...documentFixture, id: `00000000-0000-4000-8000-00000000000${index + 1}`,
    title, owner_agent_id: null, owner_user_id: 1,
    media_type: 'text/html', content_profile: 'document', payload: { text: `<p>${title} content</p>` },
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

for (const mobile of [false, true]) {
  test(`document history follows visits, branches and skips deleted documents (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
    const { items } = await library(page)
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
    await page.getByRole('link', { name: 'Open Beta', exact: true }).click()
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

test('the Documents contextual dialog action leaves the library selection and history unchanged', async ({ page }) => {
  const state = await library(page)
  state.items[0].payload.text += `<p><a href="document://${state.items[1].id}">Open Beta</a></p>`
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', {
    route: `/documents?document_id=${state.items[0].id}`, privileges: ['DOCUMENT_EDIT'],
  })
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Alpha')
  await page.getByRole('link', { name: 'Open Beta', exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Open in a dialog', exact: true }).click()
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
  await page.getByRole('link', { name: 'Open Beta', exact: true }).click()
  await expect(title).toHaveValue('Beta')
  await header.getByRole('button', { name: 'Previous document', exact: true }).click()
  await expect(title).toHaveValue('Alpha')
  await page.getByRole('link', { name: 'Open Beta', exact: true }).click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Open in a dialog', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('link', { name: 'Open Gamma', exact: true }).click()
  await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('Gamma')
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await expect(dialog).toHaveCount(0)
  await title.fill('Alpha draft after dialog')
  await header.getByRole('button', { name: 'Next document', exact: true }).click()
  await expect(title).toHaveValue('Beta')
  expect(state.writes.at(-1)).toMatchObject({ title: 'Alpha draft after dialog' })
})
