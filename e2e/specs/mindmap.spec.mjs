import { test, expect } from '@playwright/test'
import { notificationPrompt } from '../notification-prompt.mjs'
import { collectPageErrors } from '../page-errors.mjs'

test('edit and export an imported mind map in the assembled library', async ({ page, request }) => {
  test.setTimeout(120_000)
  const pageErrors = collectPageErrors(page)
  await page.addLocatorHandler(notificationPrompt(page), prompt => prompt.getByRole('button', { name: 'Plus tard', exact: true }).click())
  const seed = await request.post('/api/__test/seed')
  expect(seed.ok(), await seed.text()).toBe(true)
  const user = await seed.json()
  await page.goto('/user/login')
  await page.locator('input[type=email]').fill(user.email)
  await page.locator('input[type=password]').fill(user.password)
  const loggingIn = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
  await page.locator('button[type=submit]').click()
  const login = await loggingIn
  expect(login.ok(), await login.text()).toBe(true)
  const { access_token: token } = await login.json()
  const headers = { Authorization: `Bearer ${token}`, 'X-Editorial-Profile-Version': '1' }
  const account = await request.get('/api/auth/me', { headers })
  expect(account.ok(), await account.text()).toBe(true)

  const title = 'Synthetic field map'
  const imported = await request.post('/api/documents/import', { headers, multipart: {
    data: JSON.stringify({ owner_kind: 'user', owner_id: (await account.json()).id, title }),
    file: { name: 'field.mm', mimeType: 'application/octet-stream', buffer: Buffer.from(
      '<map version="1.0.1"><node ID="root" TEXT="Field notes"><node ID="site" TEXT="Site"/></node></map>',
    ) },
  } })
  expect(imported.ok(), await imported.text()).toBe(true)
  const document = await imported.json()
  expect(document.document_format).toBe('mindmap')

  await page.goto(`/documents?document_id=${document.id}`)
  const site = page.getByRole('treeitem', { name: 'Site', exact: true })
  await site.press('Insert')
  const branchTitle = page.getByRole('textbox', { name: /^(Titre de la branche|Branch title)$/ })
  await expect(branchTitle).toBeFocused()
  const saved = page.waitForResponse(response => response.ok() && response.url().includes(`/documents/${document.id}`)
    && response.request().method() === 'PATCH' && response.request().postData()?.includes('Measurement'))
  await branchTitle.fill('Measurement')
  await branchTitle.press('Enter')
  await saved
  await page.reload()
  await page.getByRole('treeitem', { name: 'Measurement', exact: true }).press('F2')
  await expect(branchTitle).toBeFocused()
  await page.keyboard.insertText('s')
  await expect(branchTitle).toHaveText('Measurements')
  const appended = page.waitForResponse(response => response.ok() && response.url().includes(`/documents/${document.id}`)
    && response.request().method() === 'PATCH' && response.request().postData()?.includes('Measurements'))
  await branchTitle.press('Enter')
  await appended
  await page.reload()
  const branch = page.getByRole('treeitem', { name: 'Measurements', exact: true })
  await expect(branch).toBeVisible()
  const source = await request.post('/api/documents', { headers, data: {
    owner_kind: 'user', owner_id: (await account.json()).id, title: 'Reference notes', document_format: 'text',
  } })
  expect(source.ok(), await source.text()).toBe(true)
  const sourceDocument = await source.json()
  const sourceId = sourceDocument.id
  const textContent = '<p>Calibration report</p>'
  const preparedSource = await request.patch(`/api/documents/${sourceId}`, { headers, data: {
    expected_revision: sourceDocument.revision, expected_lock_version: sourceDocument.lock_version,
    payload: { text: textContent },
  } })
  expect(preparedSource.ok(), await preparedSource.text()).toBe(true)
  const attachment = await request.post(`/api/documents/${sourceId}/attachments`, { headers, multipart: {
    file: { name: 'readings.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic readings') },
  } })
  expect(attachment.ok(), await attachment.text()).toBe(true)
  const attachmentUri = `document://${sourceId}/attachments/${(await attachment.json()).id}`
  await branch.press('Alt+Enter')
  const richEditor = branch.locator('[data-editor-surface]')
  await expect(richEditor).toBeFocused()
  await expect(richEditor).toHaveText('Measurements')
  await richEditor.press('Enter')
  await page.keyboard.insertText('Resource references')
  await page.keyboard.press('Shift+Home')
  await page.getByRole('button', { name: /^(Souligné|Underline)$/ }).click()
  await expect(richEditor.locator('u')).toHaveText('Resource references')
  await richEditor.press('End')
  await richEditor.press('Enter')
  await richEditor.evaluate((element, uri) => {
    const clipboardData = new DataTransfer()
    clipboardData.setData('text/plain', uri)
    element.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData }))
  }, attachmentUri)
  await expect(richEditor.locator(`[data-rich-reference="${attachmentUri}"]`)).toBeVisible()
  const storedBody = async () => {
    const response = await request.get(`/api/documents/${document.id}/source`, { headers })
    return (await response.json()).nodes.find(node => node.title === 'Measurements')?.body_html ?? ''
  }
  await expect.poll(storedBody).toContain(attachmentUri)
  await expect.poll(storedBody).toContain('<u>Resource references</u>')
  await richEditor.press('End')
  await richEditor.press('Enter')
  await richEditor.evaluate((element, uri) => {
    const clipboardData = new DataTransfer()
    clipboardData.setData('text/plain', uri)
    element.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData }))
  }, `document://${sourceId}`)
  const textLink = richEditor.getByRole('link', { name: 'Reference notes', exact: true })
  await textLink.click()
  await page.getByRole('button', { name: /^(Afficher le contenu intégré|Show embedded content)$/ }).click()
  await expect(richEditor.getByText('Calibration report', { exact: true })).toBeVisible()
  await expect.poll(storedBody).toContain('data-resource-mode="embed"')
  await page.getByText('Site', { exact: true }).click()
  await expect(page.locator('.mindmap-node').getByText('Resource references', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: /^(Télécharger la source|Download source)$/ }).click()
  const downloaded = page.waitForEvent('download')
  await page.getByText('FreeMind (.mm)', { exact: true }).click()
  const download = await downloaded
  expect(download.suggestedFilename()).toBe(`${title}.mm`)
  const contents = []
  for await (const chunk of await download.createReadStream()) contents.push(chunk)
  expect(Buffer.concat(contents).toString('utf8')).toContain('TEXT="Measurements"')

  const latestSource = await request.get(`/api/documents/${sourceId}`, { headers })
  expect(latestSource.ok(), await latestSource.text()).toBe(true)
  const { item: currentSource } = await latestSource.json()
  const compose = await request.patch(`/api/documents/${sourceId}`, { headers, data: {
    expected_revision: currentSource.revision, expected_lock_version: currentSource.lock_version,
    payload: { text: `${textContent}<p><a href="document://${document.id}">Field map</a></p>` },
  } })
  expect(compose.ok(), await compose.text()).toBe(true)
  await page.goto(`/documents?document_id=${sourceId}`)
  const textEditor = page.locator('[data-editor-surface]')
  await textEditor.getByRole('link', { name: 'Field map', exact: true }).click()
  await page.getByRole('button', { name: /^(Afficher le contenu intégré|Show embedded content)$/ }).click()
  const measuredBranch = textEditor.getByRole('treeitem', { name: 'Measurements', exact: true })
  await expect(measuredBranch).toBeVisible()
  await measuredBranch.getByRole('link', { name: 'Reference notes', exact: true }).scrollIntoViewIfNeeded()
  // The map refers back to this Text document. Only that inner occurrence stops.
  await expect(textEditor.getByText(/^(Ouvrir le document pour poursuivre cette référence\.|Open the document to follow this reference\.)$/)).toBeVisible()
  expect(pageErrors()).toEqual([])
})
