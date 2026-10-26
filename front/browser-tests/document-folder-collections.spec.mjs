import { test, expect, mount } from './fixtures.mjs'

test('folder collections discard late context responses and recover from failed reads', async ({ page }) => {
  const ids = ['00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002']
  const descriptor = (id, name) => ({ uri: `document://folders/${id}/`, name, is_collection: true, media_type: 'inode/directory', size: null, capabilities: ['info', 'list'], metadata: { document_folder: true, icon: 'folder:blue' } })
  const result = (id, name) => ({ folder: descriptor(id, name), entries: [{ ...descriptor(id, `${name} note`), uri: `document://${id}`, is_collection: false, media_type: 'text/html' }], total: 1 })
  let release, oldRequested = false, oldFinished
  const wait = new Promise(resolve => { release = resolve })
  const finished = new Promise(resolve => { oldFinished = resolve })
  let fail = false
  await page.route('**/api/documents/folder-collections/*?*', async route => {
    if (new URL(route.request().url()).pathname.endsWith(ids[0])) {
      oldRequested = true
      await wait
      await route.fulfill({ json: result(ids[0], 'Previous collection') }).catch(() => undefined)
      oldFinished()
    } else if (fail) await route.fulfill({ status: 403, json: { detail: 'Access revoked' } })
    else await route.fulfill({ json: result(ids[1], 'Current collection') })
  })
  await mount(page, 'app/document/components/DocumentFolderCollection.vue', { props: { folderId: ids[0] } })
  await expect.poll(() => oldRequested).toBe(true)
  await page.evaluate(folderId => window.testApp.setProps({ folderId }), ids[1])
  await expect(page.getByText('Current collection note', { exact: true })).toBeVisible()
  release(); await finished
  await expect(page.getByText('Previous collection note', { exact: true })).toHaveCount(0)
  fail = true
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('Current collection note', { exact: true })).toHaveCount(0)
  fail = false
  await page.getByRole('alert').getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('Current collection note', { exact: true })).toBeVisible()
})
