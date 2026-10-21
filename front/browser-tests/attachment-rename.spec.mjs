import { test, expect, mount } from './fixtures.mjs'

const attachment = { id: 'attachment-1', name: 'Original.txt', media_type: 'text/plain', size_bytes: 20 }

test('attachment rename validates names, preserves the failed draft and retries without changing its identity', async ({ page }) => {
  let denied = true
  const writes = []
  await page.route('**/api/memory/documents/document-1/attachments/attachment-1?*', async route => {
    expect(route.request().method()).toBe('PATCH')
    writes.push(route.request().postDataJSON())
    await route.fulfill(denied ? { status: 403, json: { detail: 'Synthetic permission denial' } }
      : { json: { ...attachment, name: writes.at(-1).name } })
  })
  await page.route('**/api/memory/documents/*/attachments/*/thumbnail?*', route => route.fulfill({ status: 204 }))
  await mount(page, 'app/memory/components/DocumentAttachments.vue', { props: {
    documentId: 'document-1', agentId: 7, attachments: [attachment], editable: true,
  } })
  await page.locator('.resource-preview-block').click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Rename Original.txt', exact: true }).click()
  const dialog = page.getByRole('dialog'), input = dialog.getByRole('textbox', { name: 'File name', exact: true })
  await expect(input).toHaveValue('Original.txt')
  await input.fill('../invalid.txt')
  await expect(dialog.getByRole('button', { name: 'Rename', exact: true })).toBeDisabled()
  expect(writes).toEqual([])
  await input.fill('Final résumé.txt')
  await input.press('Enter')
  await expect(dialog.getByRole('alert').filter({ hasText: 'Synthetic permission denial' })).toBeVisible()
  await expect(input).toHaveValue('Final résumé.txt')
  denied = false
  await dialog.getByRole('button', { name: 'Rename', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toEqual([{ name: 'Final résumé.txt' }, { name: 'Final résumé.txt' }])
  await expect.poll(() => page.evaluate(() => window.testApp.events.filter(event => event.name === 'renamed').map(event => event.value)))
    .toEqual([{ ...attachment, name: 'Final résumé.txt' }])
})

test('readonly attachments have no rename and closing a rename discards its draft', async ({ page }) => {
  await page.route('**/api/memory/documents/*/attachments/*/thumbnail?*', route => route.fulfill({ status: 204 }))
  await mount(page, 'app/memory/components/DocumentAttachments.vue', { props: {
    documentId: 'document-1', agentId: 7, attachments: [attachment], editable: false,
  } })
  await page.locator('.resource-preview-block').click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: 'Rename Original.txt', exact: true })).toHaveCount(0)
  await expect(page.getByRole('menuitem', { name: 'Remove Original.txt', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.evaluate(() => window.testApp.setProps({ editable: true }))
  await page.locator('.resource-preview-main').focus()
  await page.keyboard.press('Shift+F10')
  await page.getByRole('menuitem', { name: 'Rename Original.txt', exact: true }).click()
  await page.getByRole('textbox', { name: 'File name', exact: true }).fill('Discarded.txt')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.locator('.resource-preview-block').click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Rename Original.txt', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'File name', exact: true })).toHaveValue('Original.txt')
})
