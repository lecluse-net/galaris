import { test, expect, mount, jsonRoute } from './fixtures.mjs'
import { agent, document } from './data.mjs'

async function fixture(page, content) {
  let item = { ...document, content_profile: 'document', media_type: 'text/html', payload: { text: content } }
  await jsonRoute(page, '**/api/agents?*', [agent])
  await jsonRoute(page, '**/api/documents/owner-options?*', { agents: [{ id: 7, kind: 'agent', label: 'Alice', subtitle: '', avatar_url: null }], users: [] })
  await jsonRoute(page, '**/api/documents/keywords?*', [])
  await jsonRoute(page, '**/api/documents/doc-a/attachments?*', [])
  await page.route(/\/api\/documents\/doc-a(?:\?.*)?$/, route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { item, agent_id: 7 } })
    item = { ...item, ...route.request().postDataJSON(), revision: item.revision + 1 }
    return route.fulfill({ json: item })
  })
  return () => item.payload.text
}

const mountEditor = (page, options = {}) => mount(page, 'app/document/components/DocumentEditor.vue', {
  props: { documentId: 'doc-a', agentId: 7 }, privileges: ['DOCUMENT_EDIT'], ...options,
})

for (const { width, kind } of [{ width: 1440, kind: 'Line' }, { width: 390, kind: 'Pie' }]) {
  test(`editable charts preserve their data through autosave, reopening and PDF export (${kind})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 })
    const mobile = width < 1024
    const legacy = mobile ? '' : '<style>.legacy-note{font-weight:bold}</style><div class="legacy-note">Legacy note</div>'
    const saved = await fixture(page, legacy + '<p>Quarterly review</p>')
    const options = { route: '/documents', shell: true, dark: mobile }
    async function openDocument() {
      await mountEditor(page, options)
      if (mobile) await page.locator('.q-drawer__backdrop').click({ position: { x: width - 10, y: 200 } })
    }
    await openDocument()
    const surface = page.getByRole('textbox', { name: 'Content', exact: true })
    await surface.getByText('Quarterly review', { exact: true }).click()
    await page.keyboard.press('End')
    if (mobile) await page.getByRole('button', { name: 'More tools', exact: true }).click()
    await page.getByRole('button', { name: 'Insert chart', exact: true }).click()
    const create = page.getByRole('dialog', { name: 'Insert chart' })
    const apply = dialog => dialog.getByRole('button', { name: 'Apply', exact: true })
    await expect(apply(create)).toBeDisabled()
    await create.getByLabel('Chart title (optional)').fill('Orders < East & West')
    await create.getByLabel('Label 1', { exact: true }).fill('Winter & spring')
    await create.getByLabel('Value 1', { exact: true }).fill('12,5')
    await create.getByRole('button', { name: 'Add a value' }).click()
    await create.getByLabel('Label 2', { exact: true }).fill('Summer < fall')
    await create.getByLabel('Value 2', { exact: true }).fill('8')
    const chartName = 'Orders < East & West'
    await expect(create.getByRole('img', { name: chartName, exact: true })).toBeVisible()
    await apply(create).click()
    const figure = surface.getByRole('img', { name: chartName, exact: true })
    await expect(figure).toHaveJSProperty('complete', true)
    expect(await figure.evaluate(image => image.naturalWidth)).toBeGreaterThan(0)
    await expect.poll(saved).toContain('<svg')
    await expect(surface.getByText('Quarterly review', { exact: true })).toBeVisible()

    await page.evaluate(() => window.testApp.unmount())
    await openDocument()
    await figure.click()
    const editButton = page.getByRole('toolbar', { name: 'Contextual actions' }).getByRole('button', { name: 'Edit chart' })
    await editButton.click()
    const edit = page.getByRole('dialog', { name: 'Edit chart' })
    if (!mobile) {
      await edit.getByLabel('Value 1', { exact: true }).fill('42')
      await page.locator('.q-dialog__backdrop').click({ position: { x: 5, y: 5 } })
      await expect(edit).toBeHidden()
      await figure.click()
      await page.keyboard.press('Enter')
    }
    await expect(edit.getByLabel('Label 2', { exact: true })).toHaveValue('Summer < fall')
    await expect(edit.getByLabel('Value 1', { exact: true })).toHaveValue('12.5')
    await edit.getByRole('combobox', { name: 'Chart type' }).click()
    await page.getByRole('option', { name: kind, exact: true }).click()
    await edit.getByLabel('Value 2', { exact: true }).fill('-9')
    if (kind === 'Pie') {
      await expect(apply(edit)).toBeDisabled()
      await edit.getByLabel('Value 2', { exact: true }).fill('9')
    }
    await edit.getByLabel('Chart title (optional)').fill('Updated orders')
    await expect(edit.getByRole('img', { name: 'Updated orders', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('chart-dialog.png') })
    await apply(edit).click()
    await expect.poll(saved).toContain('Updated orders')
    await expect(surface.getByRole('img', { name: 'Updated orders', exact: true })).toHaveCount(1)
    await expect(figure).toHaveCount(0)

    let snapshot
    await page.route('**/api/documents/doc-a/export-pdf', route => {
      snapshot = route.request().postDataJSON().html
      return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.7\nfixture' })
    })
    const download = page.waitForEvent('download')
    if (mobile) await page.getByRole('button', { name: 'More tools', exact: true }).click()
    await page.getByRole('button', { name: 'Export as PDF', exact: true }).click()
    await download
    const preview = await page.context().newPage()
    await preview.setContent(snapshot)
    const exported = preview.getByRole('img', { name: 'Updated orders', exact: true })
    await expect(exported).toHaveJSProperty('complete', true)
    expect(await exported.evaluate(image => image.naturalWidth)).toBeGreaterThan(0)
    await expect(preview.getByText('Quarterly review', { exact: true })).toBeVisible()
    await preview.close()
  })
}

test.describe('document editing on touch screens', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })

  test('editing between styled SVG figures preserves their sources and captions on reopen and export', async ({ page }) => {
    const svg = name => `<svg viewBox="0 0 160 80" width="160" height="80" aria-label="${name}"><style>.bar{fill:blue}</style><defs><rect id="bar" width="96" height="24"></rect></defs><use href="#bar" class="bar"></use></svg>`
    const before = svg('First chart'), after = svg('Second chart')
    const saved = await fixture(page, `<figure>${before}<figcaption>First caption</figcaption></figure><p>Between charts</p><figure>${after}<figcaption>Second caption</figcaption></figure>`)
    await mountEditor(page)
    const surface = page.getByRole('textbox', { name: 'Content', exact: true })
    const first = surface.getByRole('img', { name: 'First chart' })
    await expect(first).toBeVisible()
    await expect(first).toHaveJSProperty('naturalWidth', 160)
    expect(await first.evaluate(image => {
      const canvas = image.ownerDocument.createElement('canvas')
      const context = canvas.getContext('2d')
      context.drawImage(image, 0, 0)
      return Array.from(context.getImageData(10, 10, 1, 1).data)
    })).toEqual([0, 0, 255, 255])
    await expect(surface.getByRole('img', { name: 'Second chart' })).toBeVisible()
    await expect(surface.locator('iframe')).toHaveCount(0)
    await surface.getByText('Between charts', { exact: true }).tap()
    await page.keyboard.press('End')
    await page.keyboard.insertText(' edited')
    await expect.poll(saved).toContain('Between charts edited')
    await surface.getByText('First caption', { exact: true }).tap()
    await page.keyboard.press('End')
    await page.keyboard.insertText(' edited')
    await expect.poll(saved).toContain('First caption edited')
    expect(saved()).toContain(before)
    expect(saved()).toContain(after)

    await page.evaluate(() => window.testApp.unmount())
    await mountEditor(page)
    await expect(surface.getByText('Between charts edited', { exact: true })).toBeVisible()
    await expect(surface.getByText('First caption edited', { exact: true })).toBeVisible()
    await expect(first).toHaveJSProperty('naturalWidth', 160)

    let snapshot
    await page.route('**/api/documents/doc-a/export-pdf', route => {
      snapshot = route.request().postDataJSON().html
      return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.7\nfixture' })
    })
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: 'More tools', exact: true }).tap()
    await page.getByRole('button', { name: 'Export as PDF', exact: true }).tap()
    await download
    const preview = await page.context().newPage()
    await preview.setContent(snapshot)
    await expect(preview.getByRole('img', { name: 'First chart' })).toHaveJSProperty('naturalWidth', 160)
    await expect(preview.getByRole('img', { name: 'Second chart' })).toHaveJSProperty('naturalWidth', 160)
    await expect(preview.getByText('Between charts edited', { exact: true })).toBeVisible()
    await expect(preview.getByText('First caption edited', { exact: true })).toBeVisible()
    await preview.close()
  })

  test('sections give separate responsive applications their own styles and leave the prose editable', async ({ page }) => {
    const block = label => `<section><style>section{display:grid;gap:8px}@media(max-width:480px){section{grid-template-columns:1fr}}</style><label>${label}<input></label><button>Apply</button><output>Ready</output><script>document.querySelector('button').onclick=()=>document.querySelector('output').textContent=document.querySelector('input').value</script></section>`
    await fixture(page, block('First answer') + '<p>Editable between applications</p>' + block('Second answer'))
    await mountEditor(page)
    const frames = page.locator('.document-application-frame')
    await expect(frames).toHaveCount(2)
    const left = frames.nth(0).contentFrame().frameLocator('iframe')
    const right = frames.nth(1).contentFrame().frameLocator('iframe')
    await expect(left.getByRole('textbox', { name: 'First answer' })).toBeVisible()
    await right.getByRole('textbox', { name: 'Second answer' }).fill('New value')
    await right.getByRole('button', { name: 'Apply' }).tap()
    await expect(right.getByRole('status')).toHaveText('New value')
    await expect(left.getByRole('status')).toHaveText('Ready')
    await expect(page.getByRole('textbox', { name: 'Content', exact: true }).getByText('Editable between applications')).toBeVisible()
  })
})
