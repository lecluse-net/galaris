import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { collectPageErrors } from '../page-errors.mjs'

for (const width of [1440, 390]) {
  test(`Office thumbnails use real conversions and preserve downloads at ${width}px`, async ({ page, request }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await page.addLocatorHandler(page.getByRole('button', { name: 'Plus tard', exact: true }),
      postpone => postpone.click())
    const errors = collectPageErrors(page)
    const fixture = await (await request.post('/api/__test/seed')).json()
    const refresh = page.waitForResponse(response => response.url().endsWith('/api/auth/refresh'))
    await page.goto('/user/login')
    await refresh
    await page.locator('input[type=email]').fill(fixture.email)
    await page.locator('input[type=password]').fill(fixture.password)
    const authentication = page.waitForResponse(response => response.url().endsWith('/api/auth/login-json'))
    await page.locator('button[type=submit]').click()
    const session = await (await authentication).json()
    await expect(page.locator('input[type=password]')).toHaveCount(0)
    const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Editorial-Profile-Version': '1' }
    const created = await request.post('/api/memory/items', { headers, data: {
      owner_agent_id: fixture.agent_id, title: 'Synthetic Office previews', node_kind: 'document',
      media_type: 'text/html', payload: { text: '<p>Office attachments with their original downloads.</p>' },
    } })
    expect(created.ok(), await created.text()).toBeTruthy()
    const document = await created.json()
    const attachments = []
    for (const name of ['synthetic-report.docx', 'synthetic-budget.ods']) {
      const original = await readFile(new URL(`../fixtures/${name}`, import.meta.url))
      const uploaded = await request.post(`/api/memory/documents/${document.id}/attachments?actor_agent_id=${fixture.agent_id}`, {
        headers, multipart: { file: { name, mimeType: 'application/octet-stream', buffer: original } },
      })
      expect(uploaded.ok(), await uploaded.text()).toBeTruthy()
      attachments.push({ ...await uploaded.json(), original })
    }
    // A link in the body must not hide its file from the attachment list.
    const latest = await request.get(`/api/memory/documents/${document.id}`, { headers })
    expect(latest.ok(), await latest.text()).toBeTruthy()
    const { item } = await latest.json()
    const reference = `document://${document.id}/attachments/${attachments[0].id}`
    const linked = await request.patch(`/api/memory/documents/${document.id}?actor_agent_id=${fixture.agent_id}`, {
      headers, data: {
        expected_revision: item.revision,
        payload: { text: `<p>Office attachments with their original downloads.</p><p><a href="${reference}">Original report</a></p>` },
      },
    })
    expect(linked.ok(), await linked.text()).toBeTruthy()
    await errors.settle()
    await page.goto(`/memory/documents?document_id=${document.id}`)
    if (width < 1024) await expect(page.getByRole('dialog')).toBeVisible()
    for (const attachment of attachments) {
      const card = page.locator('.document-attachments .resource-preview-card').filter({ has: page.getByText(attachment.name, { exact: true }) })
      await card.scrollIntoViewIfNeeded()
      const image = card.getByRole('img', { name: attachment.name, exact: true })
      await expect.poll(() => image.evaluate(element => element.naturalWidth)).toBeGreaterThan(0)
      const downloadPromise = page.waitForEvent('download')
      await card.getByRole('button', { name: new RegExp(attachment.name.replaceAll('.', '\\.')) }).first().click()
      const download = await downloadPromise
      expect(download.suggestedFilename()).toBe(attachment.name)
      const chunks = []
      for await (const chunk of await download.createReadStream()) chunks.push(chunk)
      expect(Buffer.concat(chunks)).toEqual(attachment.original)
    }
    await page.locator('.document-attachments').screenshot({ path: testInfo.outputPath('office-thumbnails.png') })
    // Reopening uses the same authorized derivative, without losing the original files.
    await errors.settle()
    await page.reload()
    for (const attachment of attachments) {
      const card = page.locator('.document-attachments .resource-preview-card').filter({ has: page.getByText(attachment.name, { exact: true }) })
      await card.scrollIntoViewIfNeeded()
      const image = card.getByRole('img', { name: attachment.name, exact: true })
      await expect(image).toBeVisible()
      await expect.poll(() => image.evaluate(element => element.naturalWidth)).toBeGreaterThan(0)
    }
    await errors.settle()
    expect(errors()).toEqual([])
  })
}
