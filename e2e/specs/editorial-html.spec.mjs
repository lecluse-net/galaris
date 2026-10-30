import { createDocument } from '../documents.mjs'
import { test, expect } from '@playwright/test'

test('editorial HTML survives real API storage, browser editing and reload', async ({ page, request }) => {
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
  const corpus = '<h2>Été</h2>' + '<p>Synthetic document paragraph</p>'.repeat(40)
    + '<p>Inline <span data-math="inline">x^2</span>.</p><p data-math="block">\\frac{a}{b}</p>'
    + '<p><u>Texte souligné</u></p><table><tbody><tr><th colspan="2" colwidth="150,200"><p>En-tête</p></th></tr><tr><td><p>A</p></td><td><p>B</p></td></tr></tbody></table><pre><code>  &lt;p&gt;\n    a  b\n</code></pre>'
  {
    const response = await request.post('/api/memory/items', { headers, data: { owner_agent_id: fixture.agent_id, title: 'HTML memory', media_type: 'text/html', payload: { text: corpus } } })
    expect(response.ok(), await response.text()).toBeTruthy()
    const item = await response.json()
    expect(item.media_type).toBe('text/html')
    expect(item.content_profile).toBe('rich-text')
  }
  // Memory keeps the static rich-text contract. Executable document isolation
  // is exercised separately by document-apps.spec.mjs.
  const documentData = { owner_agent_id: fixture.agent_id, title: 'Document HTML E2E', node_kind: 'document', media_type: 'text/html' }
  const rejected = await request.post('/api/memory/items', { headers, data: {
    ...documentData, node_kind: 'memory', title: 'Rejected scripted memory',
    payload: { text: corpus + '<script>window.editorialE2E=true</script>' },
  } })
  expect(rejected.status()).toBe(422)
  const callout = '<blockquote class="galaris-callout galaris-callout-info"><p>Document éditorial</p></blockquote>'
  const created = await createDocument(request, { headers, data: { ...documentData, payload: { text: corpus + callout } } })
  expect(created.ok(), await created.text()).toBeTruthy()
  const item = await created.json()
  const oldClient = await request.patch(`/api/documents/${item.id}?actor_agent_id=${fixture.agent_id}`, { headers: { Authorization: headers.Authorization }, data: { expected_revision: item.revision, payload: { text: 'Old client' } } })
  expect(oldClient.status()).toBe(409)
  const forbidden = await request.put(`/api/agents/${fixture.agent_id}`, { headers, data: { personality: '<img src="https://example.invalid/image.png">' } })
  expect(forbidden.status()).toBe(422)
  await page.goto(`/documents?document_id=${item.id}`)
  const editor = page.locator('.document-editor [data-editor-surface]')
  await expect(editor.locator('u')).toHaveText('Texte souligné')
  await expect(editor.locator('[data-math] .ML__latex')).toHaveCount(2)
  await page.evaluate(() => document.fonts.load('16px KaTeX_Size3'))
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  const find = page.getByRole('button', { name: /^(Find|Rechercher)$/, exact: true }).first()
  await find.click()
  const search = page.getByRole('search', { name: /^(Find|Rechercher)$/, exact: true })
  await search.getByRole('textbox', { name: /^(Find|Rechercher)$/, exact: true }).fill('Texte souligné')
  await expect(editor.locator('mark[data-search-match]')).toHaveText('Texte souligné')
  await search.getByRole('button', { name: /^(Next|Suivant)$/, exact: true }).click()
  await expect(editor.locator('[data-search-current]')).toHaveText('Texte souligné')
  await expect(editor.locator('[data-search-current]')).toBeInViewport({ ratio: 1 })
  await expect(search.getByRole('button', { name: /^(Next|Suivant)$/, exact: true })).toBeInViewport({ ratio: 1 })
  await find.click()
  await expect(search).toBeHidden()
  await expect(editor.locator('[data-search-match]')).toHaveCount(0)
  await find.click()
  await expect(search.getByRole('textbox', { name: /^(Find|Rechercher)$/, exact: true })).toHaveValue('Texte souligné')
  await find.click()
  const searched = (await (await request.get(`/api/documents/${item.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  expect(searched.revision).toBe(item.revision)
  await editor.locator('h2').click()
  await page.keyboard.press('End')
  const saved = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/documents/${item.id}`)
    && response.request().postDataJSON()?.payload?.text?.includes('<h3>Été!</h3>'))
  const modifier = await page.evaluate(() => /Macintosh|iPhone|iPad/.test(navigator.userAgent) ? 'Meta' : 'Control')
  await page.keyboard.press(`${modifier}+Alt+Digit3`)
  await expect(editor.locator('h3')).toHaveText('Été')
  await page.keyboard.type('!')
  expect((await saved).ok()).toBeTruthy()
  const persisted = (await (await request.get(`/api/documents/${item.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  expect(persisted.media_type).toBe('text/html')
  expect(persisted.payload.text).toContain('<u>Texte souligné</u>')
  expect(persisted.payload.text).toContain('colspan="2"')
  expect(persisted.payload.text).toContain('  &lt;p&gt;\n    a  b\n')
  expect(persisted.payload.text).not.toContain('<script')
  expect(persisted.payload.text).toContain('galaris-callout-info')
  expect(persisted.payload.text).toContain('<h3>Été!</h3>')
  await page.reload()
  await expect(editor.locator('h3')).toHaveText('Été!')
  await editor.locator('[data-math="inline"]').click()
  await page.getByRole('button', { name: /^(Inline equation|Équation en ligne)$/ }).click()
  const equation = page.getByRole('dialog', { name: /^(Equation editor|Éditeur d’équations)$/ })
  await equation.getByRole('textbox', { name: /^(LaTeX source|Source LaTeX)$/ }).fill('x^3')
  const formulaSaved = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/documents/${item.id}`)
    && response.request().postDataJSON()?.payload?.text?.includes('x^3'))
  await equation.getByRole('button', { name: /^(Apply|Valider)$/ }).click()
  expect((await formulaSaved).ok()).toBeTruthy()
  await page.reload()
  await expect(editor.locator('[data-math="inline"]')).toHaveAttribute('data-math-source', 'x^3')
  await expect(editor.locator('[data-math="block"] .ML__latex')).toBeVisible()
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  expect(await page.evaluate(() => window.editorialE2E)).toBeUndefined()
  await editor.locator('h3').click()
  await page.getByRole('button', { name: 'Style', exact: true }).click()
  const headingSaved = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/documents/${item.id}`)
    && response.request().postDataJSON()?.payload?.text?.includes('<h4>Été!</h4>'))
  await page.getByRole('menuitemradio', { name: /^(Heading 4|Titre 4)$/ }).click()
  expect((await headingSaved).ok()).toBeTruthy()
  await page.reload()
  await expect(editor.locator('h4')).toHaveText('Été!')
  await editor.locator('h4').click({ button: 'right' })
  const contextMenu = page.getByRole('menu', { name: /^(Content|Contenu)$/ })
  await expect(contextMenu).toBeHidden()
  await editor.locator('p').first().click({ position: { x: 5, y: 5 } })
  await expect(contextMenu).toBeHidden()
  await editor.locator('td').first().click()
  await page.getByRole('toolbar', { name: /^(Contextual actions|Actions contextuelles)$/ }).getByRole('button', { name: /^(Table properties|Propriétés du tableau)$/ }).click()
  await page.getByRole('dialog').getByRole('textbox', { name: /^(Caption|Légende)$/ }).fill('Context menu table')
  const tableSaved = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/documents/${item.id}`)
    && response.request().postDataJSON()?.payload?.text?.includes('Context menu table'))
  await page.getByRole('dialog').getByRole('button', { name: /^(Apply|Valider)$/ }).click()
  expect((await tableSaved).ok()).toBeTruthy()
  await page.reload()
  await expect(editor.locator('figcaption')).toHaveText('Context menu table')
  await expect(editor.locator('th')).toHaveAttribute('colspan', '2')
  const upload = await request.post(`/api/documents/${item.id}/attachments?actor_agent_id=${fixture.agent_id}`, {
    headers, multipart: { file: { name: 'synthetic-resize.png', mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGNkYPjPwMDAxMDAwMDAAAALHwEDmIWXfgAAAABJRU5ErkJggg==', 'base64') } },
  })
  expect(upload.ok(), await upload.text()).toBeTruthy()
  const attachment = await upload.json()
  const imageUri = `document://${item.id}/attachments/${attachment.id}`
  const latest = (await (await request.get(`/api/documents/${item.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  const imageSaved = await request.patch(`/api/documents/${item.id}?actor_agent_id=${fixture.agent_id}`, { headers, data: {
    expected_revision: latest.revision, payload: { text: latest.payload.text
      + `<figure class="image"><img width="200" alt="Synthetic resize image" src="${imageUri}"></figure><p>After image</p>` },
  } })
  expect(imageSaved.ok(), await imageSaved.text()).toBeTruthy()
  await page.reload()
  const picture = editor.getByAltText('Synthetic resize image')
  await expect(picture).toHaveJSProperty('naturalWidth', 2)
  await picture.click()
  const handle = await editor.locator('.galaris-image-resize').boundingBox()
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down()
  await page.mouse.move(handle.x + handle.width / 2 + 80, handle.y + handle.height / 2, { steps: 8 })
  const resizedWidth = (await picture.boundingBox()).width
  const resizedSave = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().includes(`/documents/${item.id}`)
    && response.request().postDataJSON()?.payload?.text?.includes('image_resized'))
  await page.mouse.up()
  expect((await resizedSave).ok()).toBeTruthy()
  const resizedDocument = (await (await request.get(`/api/documents/${item.id}?agent_id=${fixture.agent_id}`, { headers })).json()).item
  expect(resizedDocument.payload.text).toContain(imageUri)
  expect(resizedDocument.payload.text).toMatch(/width: [0-9.]+%/)
  expect(resizedDocument.payload.text).not.toMatch(/blob:|galaris-image-resize/)
  await page.reload()
  await expect(picture).toHaveJSProperty('naturalWidth', 2)
  await expect.poll(async () => (await picture.boundingBox()).width).toBeCloseTo(resizedWidth, 0)
  for (const [alignment, label] of [
    ['left', /^(Align left|Aligner à gauche)$/], ['center', /^(Center|Centrer)$/], ['right', /^(Align right|Aligner à droite)$/],
  ]) {
    await picture.click()
    const alignmentSaved = page.waitForResponse(response => response.request().method() === 'PATCH'
      && response.url().includes(`/documents/${item.id}`))
    await page.getByRole('button', { name: label, exact: true }).first().click()
    expect((await alignmentSaved).ok()).toBeTruthy()
    await page.reload()
    await expect(picture).toHaveJSProperty('naturalWidth', 2)
    await picture.scrollIntoViewIfNeeded()
    await expect.poll(() => picture.evaluate((image, alignment) => {
      const container = image.closest('.galaris-image-object').parentElement
      const bounds = container.getBoundingClientRect(), style = getComputedStyle(container), box = image.getBoundingClientRect()
      const left = box.left - bounds.left - container.clientLeft - parseFloat(style.paddingLeft)
      const right = bounds.left + container.clientLeft + container.clientWidth - parseFloat(style.paddingRight) - box.right
      return Math.abs(alignment === 'left' ? left : alignment === 'right' ? right : left - right)
    }, alignment)).toBeLessThan(2)
    await expect.poll(async () => (await picture.boundingBox()).width).toBeCloseTo(resizedWidth, 0)
  }
  await expect(page.getByRole('button', { name: 'Source', exact: true })).toHaveCount(0)
  expect(resizedDocument.payload.text).toContain('&lt;p&gt;')
  expect(await page.evaluate(() => window.editorialE2E)).toBeUndefined()
})
