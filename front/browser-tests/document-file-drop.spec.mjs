import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'
import { agent, document as fixture } from './data.mjs'
import { writeFile } from 'node:fs/promises'

async function dragFiles(page, target, files, beforeDrop) {
  const transfer = await page.evaluateHandle(files => {
    const data = new DataTransfer()
    for (const file of files) data.items.add(new File([file.content], file.name, { type: file.type, lastModified: file.lastModified ?? 1 }))
    return data
  }, files)
  await target.dispatchEvent('dragover', { dataTransfer: transfer })
  if (beforeDrop) await beforeDrop()
  await target.dispatchEvent('drop', { dataTransfer: transfer })
  await transfer.dispose()
}

async function library(page, target, options = {}) {
  const folder = { id: 'synthetic-folder', name: 'Synthetic folder', parent_id: null, position: 0, icon: null }
  const folders = [folder], createdFolders = []
  let folderFailed = false
  const parent = { ...fixture, title: 'Synthetic parent', document_type: 'data', media_type: 'application/json', payload: { text: '{}' } }
  const records = new Map([[parent.id, parent]])
  const uploads = [], placements = []
  await jsonRoute(page, '**/api/agents?*', [agent])
  await page.route('**/api/documents/tags', route => {
    if (route.request().method() === 'POST') {
      const data = route.request().postDataJSON()
      if (!folderFailed && options.failFolder === data.name) {
        folderFailed = true
        return route.fulfill({ status: 422, json: { detail: 'Synthetic folder creation failure' } })
      }
      const created = { id: `archive-folder-${createdFolders.length}`, ...data, position: 0, icon: null }
      folders.push(created); createdFolders.push(created)
      return route.fulfill({ status: 201, json: created })
    }
    return route.fulfill({ json: { user_id: 1, tags: folders } })
  })
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [], users: [{ id: 1, kind: 'user', label: 'Synthetic owner', is_current_user: true }] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await page.route('**/api/documents/library', route => {
    const request = route.request().postDataJSON()
    const entries = [...records.values()].flatMap(item => {
      const placement = placements.find(value => value.id === item.id)
      const visible = item.id === parent.id ? target === 'parent' && request.classification === 'root'
        : request.classification === 'all' || request.classification === 'root' && placement?.at_root
          || request.tag_id && placement?.tag_id === request.tag_id
          || request.parent_document_id && placement?.parent_document_id === request.parent_document_id
      return visible ? [{ item, agent_ids: item.id === parent.id ? [7] : [], writable_agent_ids: [],
        user_access: { can_read: true, can_write: true }, owner_label: 'Synthetic owner',
        parent_document_id: placement?.parent_document_id ?? null, tags: placement?.tag_id ? [folders.find(folder => folder.id === placement.tag_id)] : [], children_count: 0 }] : []
    })
    return route.fulfill({ json: { entries, total: entries.length, has_more: false, keywords: [], owners: [] } })
  })
  await page.route(/\/api\/documents\/(?:doc-a|imported-\d+)(?:\?|$)/, route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)
    return route.fulfill({ json: { item: records.get(id), agent_id: null } })
  })
  await page.route('**/api/documents/*/attachments*', route => route.fulfill({ json: [] }))
  await page.route(/\/api\/documents\/imported-\d+\/(?:tags|parent)$/, route => {
    placements.push({ id: new URL(route.request().url()).pathname.split('/').at(-2), ...route.request().postDataJSON() })
    return options.failPlacement ? route.fulfill({ status: 500, json: { detail: 'Synthetic placement failure' } }) : route.fulfill({ status: 204 })
  })
  await page.route('**/api/documents/import', async route => {
    const form = await new Response(route.request().postDataBuffer(), { headers: { 'Content-Type': route.request().headers()['content-type'] } }).formData()
    const file = form.get('file'), data = JSON.parse(form.get('data'))
    uploads.push({ data, name: file.name, content: await file.text() })
    if (options.upload) await options.upload()
    if (file.name === 'Rejected.json' && uploads.filter(value => value.name === file.name).length === 1) return route.fulfill({ status: 422, json: { detail: 'Synthetic validation failure' } })
    const attachmentOnly = file.name.endsWith('.zip')
    const item = { ...fixture, id: `imported-${uploads.length}`, title: data.title, owner_agent_id: null, owner_user_id: 1,
      document_type: attachmentOnly ? 'text' : 'data', media_type: attachmentOnly ? 'text/html' : 'application/json', payload: { text: attachmentOnly ? '' : await file.text() } }
    records.set(item.id, item)
    return route.fulfill({ status: 201, json: item })
  })
  await mount(page, 'app/document/components/DocumentLibraryPage.vue', { privileges: ['DOCUMENT_EDIT', 'DOCUMENT_ACCESS'] })
  const destination = target === 'folder' ? page.getByText('Synthetic folder', { exact: true }).locator('xpath=ancestor::div[contains(@class,"tag-row")][1]')
    : target === 'parent' ? page.getByRole('tree').getByText('Synthetic parent', { exact: true }).locator('xpath=ancestor::div[contains(@class,"document-branch-row")][1]')
      : page.getByRole('group', { name: 'Root', exact: true })
  return { uploads, placements, destination, createdFolders }
}

for (const target of ['folder', 'parent', 'root']) for (const width of [1440, 390]) {
  test(`dropping a local file creates it in ${target} and opens its editable content (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    const { uploads, placements, destination } = await library(page, target)
    await dragFiles(page, destination, [{ name: 'Synthetic values.json', type: 'application/json', content: ' {"answer":42}\n' }], async () => {
      await page.screenshot({ path: testInfo.outputPath('drop-location.png'), animations: 'disabled' })
    })
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Import documents')
    expect(uploads).toEqual([])
    await dialog.getByRole('button', { name: 'Import (1)', exact: true }).click()
    await expect(dialog.getByRole('row').filter({ hasText: 'Synthetic values.json' })).toHaveCount(0)
    await dialog.screenshot({ path: testInfo.outputPath('import-queue.png'), animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(true))
    await dialog.screenshot({ path: testInfo.outputPath('import-queue-dark.png'), animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(false))
    await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
    await expect(page.locator('textarea.code-editor')).toHaveValue(' {"answer":42}\n')
    expect(uploads).toEqual([{ data: { owner_kind: 'user', owner_id: 1, actor_agent_id: null, title: 'Synthetic values', folder: '' }, name: 'Synthetic values.json', content: ' {"answer":42}\n' }])
    expect(placements).toEqual([{ id: 'imported-1', ...(target === 'parent' ? { parent_document_id: 'doc-a' } : target === 'folder' ? { tag_id: 'synthetic-folder' } : { tag_id: null, at_root: true }) }])
    await expect(page.locator('textarea.code-editor')).toBeEditable()
    await page.screenshot({ path: testInfo.outputPath('imported-editor.png'), animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath('imported-editor-dark.png'), animations: 'disabled' })
  })
}

test('failed uploads can be retried, duplicate files stay unique and successful imports leave the queue', async ({ page }, testInfo) => {
  let release
  const { uploads, placements, destination } = await library(page, 'folder', { upload: () => new Promise(resolve => { release = resolve }) })
  await dragFiles(page, destination, [
    { name: 'Rejected.json', type: 'application/json', content: '{"rejected":true}' },
  ])
  let dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Import (1)', exact: true }).click()
  await expect.poll(() => uploads.length).toBe(1)
  await expect(dialog.getByRole('button', { name: 'Clear list', exact: true })).toBeDisabled()
  await expect(dialog.getByRole('status').filter({ hasText: 'Importing' }).last()).toContainText('Rejected.json')
  await dragFiles(page, destination, [{ name: 'Duplicate.json', type: 'application/json', content: '{}' }])
  expect(uploads).toHaveLength(1)
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await page.getByRole('button', { name: 'Import documents', exact: true }).click()
  dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Rejected.json')
  release()
  await expect(dialog.getByRole('alert').filter({ hasText: 'Synthetic validation failure' })).toBeVisible()
  expect(placements).toEqual([])
  await dialog.getByRole('button', { name: 'Import (1)', exact: true }).click()
  await expect.poll(() => uploads.length).toBe(2)
  release()
  await expect(dialog.getByRole('row').filter({ hasText: 'Rejected.json' })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  const first = { name: 'First.json', type: 'application/json', content: '{"first":1}' }
  await dragFiles(page, destination, [first, first, { name: 'Unsupported.zip', type: 'application/zip', content: 'synthetic' }])
  await dragFiles(page, destination, [first])
  dialog = page.getByRole('dialog')
  const localFile = testInfo.outputPath('Second.json')
  await writeFile(localFile, '{"second":2}')
  await dialog.locator('input[type=file]').setInputFiles(localFile)
  await dialog.locator('input[type=file]').setInputFiles(localFile)
  await expect(dialog.getByRole('row').filter({ hasText: 'First.json' })).toHaveCount(1)
  await expect(dialog.getByRole('row').filter({ hasText: 'Second.json' })).toHaveCount(1)
  // Chromium's intercepted multipart body omits disk-backed bytes. Use an in-memory
  // selection for the content check, after exercising repeated disk-file selection.
  await dialog.getByRole('button', { name: 'Remove Second.json from the list', exact: true }).click()
  await dialog.locator('input[type=file]').setInputFiles({ name: 'Second.json', mimeType: 'application/json', buffer: Buffer.from('{"second":2}') })
  const unsupported = dialog.getByRole('row').filter({ hasText: 'Unsupported.zip' })
  await unsupported.getByRole('combobox', { name: 'ZIP import mode', exact: true }).click()
  await page.getByRole('option', { name: 'Import as file', exact: true }).click()
  await expect(unsupported.getByRole('cell', { name: 'No', exact: true })).toBeVisible()
  await expect(unsupported).toContainText('Attachment only')
  await dialog.getByRole('button', { name: 'Import (3)', exact: true }).click()
  await expect.poll(() => uploads.length).toBe(3)
  release()
  await expect.poll(() => uploads.length).toBe(4)
  await expect(dialog.getByRole('row').filter({ hasText: 'First.json' })).toHaveCount(0)
  await expect(dialog.getByRole('status').filter({ hasText: 'Importing' }).last()).toContainText('Unsupported.zip')
  release()
  await expect.poll(() => uploads.length).toBe(5)
  await expect(unsupported).toHaveCount(0)
  await expect(dialog.getByRole('status').filter({ hasText: 'Importing' }).last()).toContainText('Second.json')
  release()
  await expect(dialog.getByRole('row').filter({ hasText: 'Second.json' })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Import (0)', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await expect(page.locator('textarea.code-editor')).toHaveValue('{"second":2}')
  expect(placements).toHaveLength(4)
  expect(uploads.at(-1).content).toBe('{"second":2}')
  await dragFiles(page, destination, [{ name: 'Pending.json', type: 'application/json', content: '{"pending":1}' }])
  await expect(dialog.getByRole('row').filter({ hasText: 'Pending.json' })).toHaveCount(1)
  await dialog.getByRole('button', { name: 'Clear list', exact: true }).click()
  await expect(dialog.getByRole('row').filter({ hasText: 'Pending.json' })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Import (0)', exact: true })).toBeDisabled()
  expect(uploads).toHaveLength(5)
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await setPrivileges(page, ['DOCUMENT_ACCESS'])
  await dragFiles(page, destination, [{ name: 'Denied.json', type: 'application/json', content: '{}' }])
  expect(uploads).toHaveLength(5)
})

for (const mode of ['folder', 'subfolder']) for (const width of [1440, 390]) test(`ZIP extraction into ${mode} recreates directories including empty ones (${width}px)`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 900 })
  let release
  const target = mode === 'folder' && width === 390 ? 'root' : 'folder'
  const { uploads, placements, destination, createdFolders } = await library(page, target, {
    upload: () => new Promise(resolve => { release = resolve }), failFolder: 'notes',
  })
  let expansions = 0
  await page.route('**/api/documents/import-archive', async route => {
    expansions++
    if (expansions === 1) return route.fulfill({ status: 422, json: { detail: 'Synthetic archive validation failure' } })
    const form = new FormData()
    form.append('manifest', JSON.stringify({ directories: ['empty', 'notes', 'notes/deep'], files: [
      { key: 'entry0', path: 'notes/deep/First.json', media_type: 'application/json' },
      { key: 'entry1', path: 'notes/Second.json', media_type: 'application/json' },
      { key: 'entry2', path: 'Root.json', media_type: 'application/json' },
    ] }))
    form.append('entry0', new Blob(['{"first":1}'], { type: 'application/json' }), 'entry0')
    form.append('entry1', new Blob(['{"second":2}'], { type: 'application/json' }), 'entry1')
    form.append('entry2', new Blob(['{"root":3}'], { type: 'application/json' }), 'entry2')
    const response = new Response(form)
    await route.fulfill({ headers: Object.fromEntries(response.headers), body: Buffer.from(await response.arrayBuffer()) })
  })
  await dragFiles(page, destination, [{ name: 'Bundle.zip', type: 'application/zip', content: 'synthetic archive bytes' }])
  const dialog = page.getByRole('dialog')
  const selection = dialog.getByRole('combobox', { name: 'ZIP import mode', exact: true })
  await expect(dialog.getByText('Into a dedicated subfolder', { exact: true })).toBeVisible()
  if (mode === 'folder' && width === 1440) {
    // Loading a root language catalog must not erase the import surface's messages.
    await page.evaluate(async () => { const { setLocale } = await import('/core/i18n/index.ts'); await setLocale('fr') })
    await expect(dialog.getByText('Importer des documents', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('combobox', { name: 'Mode d’import du ZIP', exact: true })).toBeVisible()
    await page.evaluate(async () => { const { setLocale } = await import('/core/i18n/index.ts'); await setLocale('en') })
    await expect(dialog.getByText('Into a dedicated subfolder', { exact: true })).toBeVisible()
  }
  if (mode === 'folder') {
    await selection.click()
    await page.getByRole('option', { name: 'Into the current folder', exact: true }).click()
    await expect(dialog.getByText('Into a dedicated subfolder', { exact: true })).toHaveCount(0)
  }
  await dialog.screenshot({ path: testInfo.outputPath('zip-import.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await dialog.screenshot({ path: testInfo.outputPath('zip-import-dark.png'), animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(false))
  await dialog.getByRole('button', { name: 'Import (1)', exact: true }).click()
  await expect(dialog.getByRole('alert').filter({ hasText: 'Synthetic archive validation failure' })).toBeVisible()
  expect(createdFolders).toEqual([])
  await dialog.getByRole('button', { name: 'Import (1)', exact: true }).click()
  await expect(dialog.getByRole('alert').filter({ hasText: 'Synthetic folder creation failure' })).toBeVisible()
  expect(createdFolders.map(folder => folder.name)).toEqual(mode === 'subfolder' ? ['Bundle', 'empty'] : ['empty'])
  expect(uploads).toHaveLength(0)
  await dialog.getByRole('button', { name: 'Import (1)', exact: true }).click()
  await expect.poll(() => uploads.length).toBe(1)
  expect(expansions).toBe(2)
  const parentId = target === 'root' ? null : 'synthetic-folder'
  const rootFolder = createdFolders.find(folder => folder.name === 'Bundle')
  if (mode === 'subfolder') expect(rootFolder).toEqual(expect.objectContaining({ parent_id: parentId }))
  else expect(rootFolder).toBeUndefined()
  const baseId = rootFolder?.id ?? parentId
  const notesFolder = createdFolders.find(folder => folder.name === 'notes')
  const deepFolder = createdFolders.find(folder => folder.name === 'deep')
  expect(createdFolders.find(folder => folder.name === 'empty').parent_id).toBe(baseId)
  expect(notesFolder.parent_id).toBe(baseId)
  expect(deepFolder.parent_id).toBe(notesFolder.id)
  await expect(dialog.getByRole('status').filter({ hasText: 'Importing' }).last()).toContainText('Bundle.zip/notes/deep/First.json')
  release()
  await expect.poll(() => uploads.length).toBe(2)
  release()
  await expect.poll(() => uploads.length).toBe(3)
  release()
  await expect(dialog.getByRole('row').filter({ hasText: 'Bundle.zip' })).toHaveCount(0)
  expect(uploads.map(file => [file.name, file.content])).toEqual([['First.json', '{"first":1}'], ['Second.json', '{"second":2}'], ['Root.json', '{"root":3}']])
  expect(placements).toEqual([{ id: 'imported-1', tag_id: deepFolder.id }, { id: 'imported-2', tag_id: notesFolder.id },
    { id: 'imported-3', tag_id: baseId, ...(baseId === null ? { at_root: true } : {}) }])
})

test('a failed placement keeps the created document editable and reports its location', async ({ page }) => {
  const { destination } = await library(page, 'folder', { failPlacement: true })
  await dragFiles(page, destination, [{ name: 'Recoverable.json', type: 'application/json', content: '{"kept":true}' }])
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Import (1)', exact: true }).click()
  await expect(dialog.getByRole('row').filter({ hasText: 'Recoverable.json' })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click()
  await expect(page.locator('textarea.code-editor')).toHaveValue('{"kept":true}')
  await expect(page.getByText(/document was created.*could not be placed/i)).toBeVisible()
})
